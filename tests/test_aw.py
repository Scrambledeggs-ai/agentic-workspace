"""Pruebas de aw. Solo biblioteca estándar: python3 -m unittest discover -s tests -v

Cada prueba trabaja en un workspace temporal (AW_HOME) y en un TMPDIR propio,
así que nunca toca el workspace real ni los archivos de sesión reales.
"""
import hashlib
import importlib.util
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "generate.py")
HOOK_EVENTS = ["SessionStart", "PostToolUse", "PostToolUseFailure", "PreCompact", "Stop", "SessionEnd"]


def slurp(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_aw(workspace):
    """Importa generate.py como módulo con AW_HOME apuntando al workspace de prueba."""
    previous = os.environ.get("AW_HOME")
    os.environ["AW_HOME"] = workspace
    try:
        spec = importlib.util.spec_from_file_location(f"aw_under_test_{abs(hash(workspace))}", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("AW_HOME", None)
        else:
            os.environ["AW_HOME"] = previous


class AwCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aw-test-")
        self.ws = os.path.join(self.tmp, "ws")
        self.sessions = os.path.join(self.tmp, "tmp")
        os.makedirs(self.sessions)
        self.env = dict(os.environ, AW_HOME=self.ws, TMPDIR=self.sessions)
        self.env.pop("CLAUDE_PROJECT_DIR", None)
        self.env.pop("AW_PROJECT", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- utilidades --
    def aw(self, *args, cwd=None, stdin=None):
        return subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd or self.tmp, env=self.env,
                              input=stdin, capture_output=True, text=True)

    def init(self):
        result = self.aw("init")
        self.assertEqual(result.returncode, 0, result.stderr)

    def new_project(self, name="demo", desc="Proyecto de prueba"):
        self.init()
        result = self.aw("project", "new", name, "--desc", desc)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.project(name)

    def project(self, name="demo"):
        return os.path.join(self.ws, "projects", name)

    def read(self, project, *parts):
        with open(os.path.join(project, *parts), encoding="utf-8") as f:
            return f.read()

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def hook(self, event, payload, cwd):
        return self.aw("hook", event, cwd=cwd, stdin=json.dumps(payload))

    def git(self, cwd, *args):
        result = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                cwd=cwd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def template_files(self):
        base = os.path.join(self.ws, "projects", "template_project")
        found = []
        for dirpath, _dirs, files in os.walk(base):
            for fname in files:
                found.append(os.path.join(dirpath, fname))
        return found


class TestSintaxis(unittest.TestCase):
    def test_compila(self):
        py_compile.compile(SCRIPT, doraise=True)

    def test_structure_json_valido(self):
        with open(os.path.join(REPO, "structure.json"), encoding="utf-8") as f:
            data = json.load(f)
        template = data["projects"]["folders"]["template_project"]
        self.assertIn("skills", template["folders"])
        self.assertIn("assigned_tools.md", template["folders"]["tools"]["files"])
        self.assertEqual(sorted(template["folders"]), sorted([".claude", "tasks", "execution", "agents", "skills", "tools", "artifacts", "sop"]))


class TestEstructura(AwCase):
    def test_init_crea_plantilla_con_contenido(self):
        self.init()
        files = self.template_files()
        self.assertGreaterEqual(len(files), 26)
        for path in files:
            self.assertGreater(os.path.getsize(path), 0, f"vacío: {path}")

    def test_json_de_la_plantilla_son_validos(self):
        self.init()
        base = os.path.join(self.ws, "projects", "template_project")
        for rel in (".claude/settings.json", "context_index.json", "tools/tool_state.json"):
            with open(os.path.join(base, rel), encoding="utf-8") as f:
                json.load(f)

    def test_claude_md_de_workspace(self):
        self.init()
        text = slurp(os.path.join(self.ws, "CLAUDE.md"))
        self.assertIn("Aplica solo a proyectos aw", text.splitlines()[2])
        self.assertNotIn("@@", text)
        self.assertIn(os.path.join(self.ws, "agents"), text)
        for pointer in ("core/config.md", "memory/global.md", "memory/projects/project_index.md"):
            self.assertIn(os.path.join(self.ws, pointer), text)
        self.assertIn("Si están vacíos o sin completar, ignóralos", text)

    def test_init_no_pisa_contenido_y_rellena_vacios(self):
        self.init()
        base = os.path.join(self.ws, "projects", "template_project")
        custom = os.path.join(base, "sop", "rules.md")
        self.write(custom, "mis reglas\n")
        empty = os.path.join(base, "sop", "workflow.md")
        self.write(empty, "")
        self.init()
        self.assertEqual(slurp(custom), "mis reglas\n")
        self.assertIn("Flujo de trabajo", slurp(empty))

    def test_archivos_sin_plantilla_siguen_igual(self):
        self.init()
        self.assertEqual(os.path.getsize(os.path.join(self.ws, "logs", "debug.md")), 0)
        self.assertEqual(os.path.getsize(os.path.join(self.ws, "logs", "current_month.md")), 0)
        header = slurp(os.path.join(self.ws, "agents", "coding_agent.md"))
        self.assertTrue(header.startswith("---\nname: Coding Agent"))

    CORE_Y_MEMORY = ("core/init.md", "core/agent.md", "core/config.md", "core/router.md", "core/memory_policy.md",
                     "memory/global.md", "memory/user_profile.md", "memory/preferences.md")

    def test_core_y_memory_se_crean_con_formato_base(self):
        self.init()
        for rel in self.CORE_Y_MEMORY:
            text = slurp(os.path.join(self.ws, *rel.split("/")))
            self.assertTrue(text.startswith("# "), rel)
            self.assertIn("<!--", text, rel)
            self.assertNotIn("@@", text, rel)
        for rel in ("core/config.md", "core/router.md", "core/init.md"):
            self.assertIn("(completar)", slurp(os.path.join(self.ws, *rel.split("/"))), rel)
        # Los que remiten a otra fuente lo dicen, en vez de duplicar contenido.
        self.assertIn("CLAUDE.md", slurp(os.path.join(self.ws, "memory", "user_profile.md")))
        self.assertIn("no duplica", slurp(os.path.join(self.ws, "memory", "preferences.md")))

    def test_core_y_memory_no_pisan_lo_que_ya_tiene_contenido_y_rellenan_vacios(self):
        self.init()
        mine = os.path.join(self.ws, "core", "config.md")
        self.write(mine, "# Mi configuración\nrutas mías\n")
        empty = os.path.join(self.ws, "core", "router.md")
        self.write(empty, "")
        self.init()
        self.assertEqual(slurp(mine), "# Mi configuración\nrutas mías\n")
        self.assertIn("Enrutamiento de tareas", slurp(empty))

    def test_los_formatos_de_core_y_memory_no_traen_datos_personales(self):
        base = os.path.join(REPO, "templates")
        for rel in self.CORE_Y_MEMORY:
            text = slurp(os.path.join(base, *rel.split("/"))).lower()
            for forbidden in ("/home/", "@", os.path.basename(os.path.expanduser("~")).lower()):
                self.assertNotIn(forbidden, text, rel)

    def test_proyecto_nuevo_sin_marcadores_ni_vacios(self):
        project = self.new_project()
        for dirpath, _dirs, files in os.walk(project):
            for fname in files:
                path = os.path.join(dirpath, fname)
                self.assertGreater(os.path.getsize(path), 0, f"vacío: {path}")
                self.assertNotIn("@@", slurp(path), f"marcador sin resolver: {path}")
        self.assertIn("# demo", self.read(project, "project.md"))
        self.assertIn("Proyecto de prueba", self.read(project, "project.md"))
        self.assertIn("CLAUDE.md — demo", self.read(project, "CLAUDE.md"))
        self.assertTrue(self.read(project, "state.md").startswith("Estado: 0 en curso"))
        self.assertIn("[nota] proyecto creado", self.read(project, "state.md"))

    def test_siete_carpetas_y_notas_de_asignacion(self):
        project = self.new_project()
        for folder in ("agents", "skills", "tools", "artifacts", "execution", "sop", "tasks"):
            self.assertTrue(os.path.isdir(os.path.join(project, folder)), folder)
        for rel in ("agents/assigned_agents.md", "agents/agent_context.md", "skills/assigned_skills.md",
                    "skills/skill_context.md", "tools/assigned_tools.md", "tools/tool_usage.md", "tools/tool_state.json"):
            self.assertTrue(os.path.isfile(os.path.join(project, rel)), rel)

    def test_settings_del_proyecto_tienen_hooks_permisos_y_ruta_al_script(self):
        project = self.new_project()
        settings = json.loads(self.read(project, ".claude", "settings.json"))
        for event in HOOK_EVENTS:
            self.assertIn(event, settings["hooks"])
            command = settings["hooks"][event][0]["hooks"][0]["command"]
            self.assertIn(SCRIPT, command)
            self.assertIn(" hook ", command)
        self.assertEqual(settings["permissions"]["allow"], ["Bash(aw task *)", "Bash(aw decide *)", "Bash(aw log *)"])
        self.assertEqual(settings["permissions"]["additionalDirectories"],
                         [os.path.join(self.ws, d) for d in ("agents", "skills", "tools", "core", "memory")])

    def test_hooks_de_herramientas_no_son_async(self):
        project = self.new_project()
        settings = json.loads(self.read(project, ".claude", "settings.json"))
        for event in ("PostToolUse", "PostToolUseFailure"):
            for group in settings["hooks"][event]:
                for hook in group["hooks"]:
                    self.assertFalse(hook.get("async"), event)

    def test_nombres_invalidos(self):
        self.init()
        for bad in ("../fuera", "template_project", ".oculto"):
            result = self.aw("project", "new", bad)
            self.assertEqual(result.returncode, 2, bad)
        self.assertEqual(self.aw("project", "new", "a").returncode, 0)
        self.assertEqual(self.aw("project", "new", "a").returncode, 2)

    def test_project_new_sin_init_da_error_claro(self):
        result = self.aw("project", "new", "x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("aw init", result.stderr)

    def test_menu_sigue_funcionando(self):
        self.new_project()
        listing = self.aw(stdin="2\n0\n")
        self.assertEqual(listing.returncode, 0)
        self.assertIn("- demo: Estado: 0 en curso", listing.stdout)
        doctor = self.aw(stdin="10\n0\n")
        self.assertIn("aw doctor", doctor.stdout)
        sync = self.aw(stdin="11\ns\n0\n")
        self.assertIn("Modo prueba", sync.stdout)
        agents = self.aw(stdin="6\na\nc\n0\n")
        self.assertIn("Coding Agent", agents.stdout)


class TestTareas(AwCase):
    def task_lines(self, project, name):
        return [l for l in self.read(project, "tasks", name).splitlines() if re.match(r"- \[[ x]\] T-\d+", l)]

    def test_add_ordena_por_prioridad_y_numera(self):
        project = self.new_project()
        self.assertEqual(self.aw("task", "add", "tarea normal", cwd=project).stdout.strip(), "T-001 creada [P2]")
        self.aw("task", "add", "urgente", "--prio", "P0", cwd=project)
        self.aw("task", "add", "otra normal", cwd=project)
        self.aw("task", "add", "baja", "--prio", "p3", cwd=project)
        lines = [l for l in self.read(project, "tasks", "backlog.md").splitlines() if l.startswith("- [ ]")]
        self.assertEqual([re.search(r"T-\d+", l).group(0) for l in lines], ["T-002", "T-001", "T-003", "T-004"])
        self.assertTrue(self.read(project, "tasks", "backlog.md").startswith("# Pendientes"))

    def test_start_y_done_mueven_la_tarea(self):
        project = self.new_project()
        self.aw("task", "add", "hacer algo", "--prio", "P1", cwd=project)
        self.assertIn("en curso", self.aw("task", "start", "T-001", cwd=project).stdout)
        self.assertEqual(self.task_lines(project, "backlog.md"), [])
        self.assertIn("(iniciada", self.read(project, "tasks", "active.md"))
        self.assertIn("hecha", self.aw("task", "done", "t1", cwd=project).stdout)
        self.assertEqual(self.task_lines(project, "active.md"), [])
        done = self.read(project, "tasks", "done.md")
        self.assertIn("- [x] T-001 [P1] hacer algo (creada", done)
        self.assertIn("(hecha", done)

    def test_done_directo_desde_pendientes(self):
        project = self.new_project()
        self.aw("task", "add", "rápida", cwd=project)
        self.assertEqual(self.aw("task", "done", "T-001", cwd=project).returncode, 0)
        self.assertIn("T-001", self.read(project, "tasks", "done.md"))

    def test_errores_de_tareas(self):
        project = self.new_project()
        self.assertEqual(self.aw("task", "start", "T-009", cwd=project).returncode, 2)
        self.assertEqual(self.aw("task", "done", "xx", cwd=project).returncode, 2)
        self.assertEqual(self.aw("task", "add", "", cwd=project).returncode, 2)
        self.assertEqual(self.aw("task", "add", "algo", "--prio", "P9", cwd=project).returncode, 2)
        self.aw("task", "add", "a", cwd=project)
        self.aw("task", "start", "T-001", cwd=project)
        self.assertIn("ya está en curso", self.aw("task", "start", "T-001", cwd=project).stderr)
        self.aw("task", "done", "T-001", cwd=project)
        self.assertIn("ya está hecha", self.aw("task", "done", "T-001", cwd=project).stderr)
        self.assertIn("ya está hecha", self.aw("task", "start", "T-001", cwd=project).stderr)

    def test_los_ids_no_se_reutilizan(self):
        project = self.new_project()
        self.aw("task", "add", "uno", cwd=project)
        self.aw("task", "done", "T-001", cwd=project)
        self.assertEqual(self.aw("task", "add", "dos", cwd=project).stdout.strip(), "T-002 creada [P2]")

    def test_titulo_multilinea_se_normaliza(self):
        project = self.new_project()
        self.aw("task", "add", "línea uno\nlínea dos", cwd=project)
        self.assertIn("T-001 [P2] línea uno línea dos", self.read(project, "tasks", "backlog.md"))

    def test_list_muestra_secciones(self):
        project = self.new_project()
        self.aw("task", "add", "a", "--prio", "P1", cwd=project)
        self.aw("task", "add", "b", cwd=project)
        self.aw("task", "start", "T-001", cwd=project)
        out = self.aw("task", "list", cwd=project).stdout
        self.assertIn("En curso:\n  T-001 [P1] a", out)
        self.assertIn("Pendientes:\n  T-002 [P2] b", out)
        self.assertNotIn("Hechas", out)
        self.assertIn("Hechas:", self.aw("task", "list", "--all", cwd=project).stdout)

    def test_state_refleja_las_tareas(self):
        project = self.new_project()
        self.aw("task", "add", "a", "--prio", "P1", cwd=project)
        self.aw("task", "add", "b", cwd=project)
        self.aw("task", "start", "T-001", cwd=project)
        state = self.read(project, "state.md")
        self.assertTrue(state.startswith("Estado: 1 en curso · 1 pendientes · 0 hechas"))
        self.assertIn("- T-001 [P1] a\n", state)
        self.assertNotIn("(iniciada", state)

    def test_funciona_desde_subcarpeta_y_con_project(self):
        project = self.new_project()
        sub = os.path.join(project, "artifacts", "x")
        os.makedirs(sub)
        self.assertEqual(self.aw("task", "add", "desde sub", cwd=sub).returncode, 0)
        self.assertEqual(self.aw("task", "add", "por nombre", "--project", "demo", cwd=self.tmp).returncode, 0)
        self.assertIn("por nombre", self.read(project, "tasks", "backlog.md"))

    def test_state_a_mano_que_menciona_la_marca_no_se_regenera(self):
        project = self.new_project()
        manual = "Estado: mío\nRecordatorio: los archivos con aw:auto los genera aw\n"
        self.write(os.path.join(project, "state.md"), manual)
        self.aw("task", "add", "algo", cwd=project)
        self.assertEqual(self.read(project, "state.md"), manual)

    def test_no_escribe_fuera_de_un_proyecto(self):
        self.new_project()
        outside = self.aw("task", "add", "x", cwd=self.tmp)
        self.assertEqual(outside.returncode, 2)
        self.assertIn("No se está dentro de un proyecto aw", outside.stderr)
        for bad in ("../demo", "nada", ".x", "a/b"):
            self.assertEqual(self.aw("task", "add", "x", "--project", bad, cwd=self.tmp).returncode, 2, bad)
        template = self.aw("task", "add", "x", "--project", "template_project", cwd=self.tmp)
        self.assertEqual(template.returncode, 2)
        self.assertIn("plantilla", template.stderr)
        self.assertEqual(self.aw("task", "add", "x", cwd=os.path.join(self.ws, "projects", "template_project")).returncode, 2)


class TestDecisionesYRegistro(AwCase):
    def test_decide_registra_con_motivo_y_alternativas(self):
        project = self.new_project()
        result = self.aw("decide", "Usar Python", "--why", "sin dependencias", "--alt", "Node", cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.read(project, "execution", "decisions.md")
        self.assertRegex(text, r"## \d{4}-\d{2}-\d{2} — Usar Python\n- Motivo: sin dependencias\n- Alternativas: Node\n")
        self.assertIn("[decisión] Usar Python", self.read(project, "execution", "run_log.md"))
        self.assertIn("## Última decisión\n- ", self.read(project, "state.md"))
        self.assertIn("Usar Python", self.read(project, "state.md"))

    def test_decide_exige_motivo(self):
        project = self.new_project()
        self.assertNotEqual(self.aw("decide", "algo", cwd=project).returncode, 0)
        blank = self.aw("decide", "algo", "--why", "   ", cwd=project)
        self.assertEqual(blank.returncode, 2)
        self.assertIn("motivo", blank.stderr)
        self.assertNotIn("algo", self.read(project, "execution", "decisions.md"))

    def test_log_agrega_nota(self):
        project = self.new_project()
        self.assertEqual(self.aw("log", "revisé", "el", "brief", cwd=project).returncode, 0)
        self.assertIn("[nota] revisé el brief", self.read(project, "execution", "run_log.md"))

    def test_state_manual_no_se_pisa(self):
        project = self.new_project()
        self.write(os.path.join(project, "state.md"), "Estado: lo escribí yo\n")
        self.aw("task", "add", "algo", cwd=project)
        result = self.aw("state", cwd=project)
        self.assertEqual(self.read(project, "state.md"), "Estado: lo escribí yo\n")
        self.assertIn("texto manual", result.stderr)

    def test_state_heredado_se_reemplaza(self):
        project = self.new_project()
        self.write(os.path.join(project, "state.md"), "Estado: iniciado\n")
        self.aw("state", "--quiet", cwd=project)
        self.assertTrue(self.read(project, "state.md").startswith("Estado: 0 en curso"))
        self.write(os.path.join(project, "state.md"), "")
        self.aw("state", "--quiet", cwd=project)
        self.assertIn("aw:auto", self.read(project, "state.md"))

    def test_menu_muestra_decisiones_y_tareas(self):
        project = self.new_project()
        self.aw("decide", "Elegir X", "--why", "porque sí", cwd=project)
        self.aw("task", "add", "pendiente 1", cwd=project)
        self.aw("task", "start", "T-001", cwd=project)
        self.assertIn("Elegir X", self.aw(stdin="4\n1\n0\n").stdout)
        self.assertIn("T-001", self.aw(stdin="3\n1\n0\n").stdout)

    def test_rotacion_del_registro(self):
        project = self.new_project()
        aw = load_aw(self.ws)
        for i in range(450):
            aw.log_event(project, "nota", f"evento {i}")
        lines = self.read(project, "execution", "run_log.md").splitlines()
        self.assertTrue(lines[0].startswith("# Registro de ejecución"))
        self.assertLessEqual(sum(1 for l in lines if l.startswith("- ")), 400)
        self.assertIn("evento 449", "\n".join(lines))
        archive = self.read(project, "execution", "run_log_archivo.md")
        self.assertIn("evento 0", archive)
        self.assertNotIn("evento 449", archive)


class TestHooks(AwCase):
    def payload(self, project, **extra):
        data = {"session_id": "s1", "cwd": project}
        data.update(extra)
        return data

    def test_session_start_carga_contexto(self):
        project = self.new_project()
        self.aw("task", "add", "tarea activa", "--prio", "P1", cwd=project)
        self.aw("task", "start", "T-001", cwd=project)
        result = self.hook("session-start", self.payload(project, source="startup"), project)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        context = output["additionalContext"]
        self.assertIn("Proyecto demo", context)
        self.assertIn("T-001 [P1] tarea activa", context)
        self.assertIn("iniciada (startup)", context)
        self.assertNotIn("aw:auto", context)
        self.assertLessEqual(len(context.splitlines()), 45)
        self.assertIn("[sesión] iniciada (startup)", self.read(project, "execution", "run_log.md"))

    def test_session_start_limita_el_tamano(self):
        project = self.new_project()
        aw = load_aw(self.ws)
        for i in range(200):
            aw.log_event(project, "nota", "x" * 300 + str(i))
        context = json.loads(self.hook("session-start", self.payload(project), project).stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(context), 4000)

    def test_session_start_desde_subcarpeta(self):
        project = self.new_project()
        sub = os.path.join(project, "sop")
        result = self.hook("session-start", {"session_id": "s2", "cwd": sub}, sub)
        self.assertIn("Proyecto demo", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_hooks_fuera_de_proyecto_son_silenciosos(self):
        self.new_project()
        for event in ("session-start", "post-tool", "tool-failure", "pre-compact", "stop", "session-end"):
            result = self.hook(event, {"session_id": "z", "cwd": self.tmp}, self.tmp)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""), event)

    def test_hooks_no_tocan_la_plantilla(self):
        self.new_project()
        template = os.path.join(self.ws, "projects", "template_project")
        before = self.read(template, "execution", "run_log.md")
        self.hook("session-start", {"session_id": "t", "cwd": template}, template)
        self.hook("session-end", {"session_id": "t", "cwd": template}, template)
        self.assertEqual(self.read(template, "execution", "run_log.md"), before)

    def test_hooks_toleran_entrada_basura_y_eventos_desconocidos(self):
        project = self.new_project()
        for event in ("session-start", "stop", "session-end", "no-existe", ""):
            result = self.aw("hook", event, cwd=project, stdin="esto no es json {{{")
            self.assertEqual(result.returncode, 0, event)
        self.assertEqual(self.aw("hook", cwd=project, stdin="").returncode, 0)

    def test_post_tool_registra_solo_commits(self):
        project = self.new_project()
        self.git(project, "init", "-q")
        self.git(project, "add", ".")
        self.git(project, "commit", "-q", "-m", "primer commit de prueba")
        run_log = os.path.join(project, "execution", "run_log.md")
        before = self.read(project, "execution", "run_log.md")
        for command in ("ls -la", "git log --grep commit", "echo git commit-tree", "git status"):
            self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={"command": command}), project)
        self.assertEqual(slurp(run_log), before)
        self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={"command": 'git commit -m "x"'}), project)
        self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={"command": "cd sub && git -c user.name=a commit -m y"}), project)
        entries = [l for l in self.read(project, "execution", "run_log.md").splitlines() if "[commit]" in l]
        self.assertEqual(len(entries), 2)
        self.assertIn("primer commit de prueba", entries[0])

    def test_tool_failure_guarda_solo_primera_linea_y_sin_secretos(self):
        project = self.new_project()
        secret_command = "curl -H 'Authorization: Bearer abc123SECRETVALUE' https://x.test"
        error = "curl: (6) Could not resolve host\nsegunda línea que no debe guardarse"
        self.hook("tool-failure", self.payload(project, tool_name="Bash", tool_input={"command": secret_command}, error=error), project)
        text = self.read(project, "execution", "errors.md")
        self.assertRegex(text, r"- \d{4}-\d{2}-\d{2} \d{2}:\d{2} \[Bash\] curl: \(6\) Could not resolve host\n")
        self.assertNotIn("segunda línea", text)
        self.assertNotIn("abc123SECRETVALUE", text)
        self.assertNotIn("Authorization", text)
        self.hook("tool-failure", self.payload(project, tool_name="Bash", error="fallo con Authorization: Bearer abc123SECRETVALUE y password=hunter2"), project)
        text = self.read(project, "execution", "errors.md")
        self.assertNotIn("abc123SECRETVALUE", text)
        self.assertNotIn("hunter2", text)

    def test_tool_failure_une_codigo_de_salida_con_el_motivo(self):
        # Formato real que entrega Claude Code: "Exit code N" en la primera línea y el motivo en la segunda.
        project = self.new_project()
        error = "Exit code 2\nls: cannot access './no-existe': No such file or directory"
        self.hook("tool-failure", self.payload(project, tool_name="Bash", tool_input={"command": "ls ./no-existe"}, error=error), project)
        self.assertIn("[Bash] Exit code 2 — ls: cannot access './no-existe': No such file or directory\n", self.read(project, "execution", "errors.md"))
        self.assertNotIn("ls ./no-existe", self.read(project, "execution", "errors.md"))  # el comando no se guarda

    def test_tool_failure_acepta_respuesta_no_textual(self):
        project = self.new_project()
        self.hook("tool-failure", self.payload(project, tool_name="Edit", tool_response={"error": "no se pudo"}), project)
        self.assertIn("[Edit]", self.read(project, "execution", "errors.md"))

    def test_pre_compact_registra_y_actualiza_estado(self):
        project = self.new_project()
        self.aw("task", "add", "algo", cwd=project)
        self.hook("pre-compact", self.payload(project, trigger="auto"), project)
        self.assertIn("[compactación] auto", self.read(project, "execution", "run_log.md"))

    def test_stop_avisa_una_sola_vez_si_hay_commits_sin_registro(self):
        project = self.new_project()
        self.git(project, "init", "-q")
        self.git(project, "add", ".")
        self.git(project, "commit", "-q", "-m", "c1")
        self.hook("session-start", self.payload(project), project)
        silent = self.hook("stop", self.payload(project), project)
        self.assertEqual(silent.stdout, "")
        self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={"command": "git commit -m c1"}), project)
        first = self.hook("stop", self.payload(project), project)
        message = json.loads(first.stdout)["systemMessage"]
        self.assertIn("1 commit(s)", message)
        self.assertIn("aw decide", message)
        self.assertEqual(self.hook("stop", self.payload(project), project).stdout, "")

    def test_stop_no_avisa_si_se_registro_algo(self):
        project = self.new_project()
        self.git(project, "init", "-q")
        self.git(project, "add", ".")
        self.git(project, "commit", "-q", "-m", "c1")
        self.hook("session-start", self.payload(project), project)
        self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={"command": "git commit -m c1"}), project)
        self.aw("decide", "Algo", "--why", "porque", cwd=project)
        self.assertEqual(self.hook("stop", self.payload(project), project).stdout, "")

    def commit_in_session(self, project):
        self.git(project, "init", "-q")
        self.git(project, "add", ".")
        self.git(project, "commit", "-q", "-m", "c1")
        self.hook("session-start", self.payload(project), project)
        self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={"command": "git commit -m c1"}), project)

    def test_session_start_al_reanudar_no_repite_el_aviso(self):
        project = self.new_project()
        self.commit_in_session(project)
        self.assertIn("systemMessage", self.hook("stop", self.payload(project), project).stdout)
        self.hook("session-start", self.payload(project, source="compact"), project)
        self.assertEqual(self.hook("stop", self.payload(project), project).stdout, "")

    def test_session_start_al_compactar_no_pierde_lo_registrado(self):
        project = self.new_project()
        self.commit_in_session(project)
        self.aw("decide", "Algo", "--why", "porque", cwd=project)
        self.hook("session-start", self.payload(project, source="compact"), project)
        self.assertEqual(self.hook("stop", self.payload(project), project).stdout, "")

    def test_session_start_de_una_sesion_nueva_descarta_lo_que_dejo_otra_sin_cierre(self):
        project = self.new_project()
        self.git(project, "init", "-q")
        self.git(project, "add", ".")
        self.git(project, "commit", "-q", "-m", "c1")
        self.hook("session-start", {"cwd": project}, project)
        self.hook("post-tool", {"cwd": project, "tool_name": "Bash", "tool_input": {"command": "git commit -m c1"}}, project)
        # Esa sesión termina sin SessionEnd; llega una nueva, también sin session_id.
        self.hook("session-start", {"cwd": project, "source": "startup"}, project)
        self.assertEqual(self.hook("stop", {"cwd": project}, project).stdout, "")

    def test_session_end_espera_si_el_workspace_esta_bloqueado(self):
        project = self.new_project()
        aw = load_aw(self.ws)
        with aw.project_lock(self.ws):
            proc = subprocess.Popen([sys.executable, SCRIPT, "hook", "session-end"], cwd=project, env=self.env,
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            self.addCleanup(proc.kill)
            proc.stdin.write(json.dumps(self.payload(project)))
            proc.stdin.close()
            time.sleep(0.7)
            self.assertIsNone(proc.poll(), "el cierre no debe tocar el registro mensual con el workspace bloqueado")
        proc.wait(timeout=20)
        self.assertIn("demo — terminada", self.read(self.ws, "logs", "current_month.md"))

    def test_hooks_sin_session_id_no_comparten_temporales_entre_proyectos(self):
        a = self.new_project("a")
        self.aw("project", "new", "b")
        b = self.project("b")
        self.hook("post-tool", {"cwd": a, "tool_name": "Bash", "tool_input": {}}, a)
        self.hook("session-end", {"cwd": b}, b)
        self.assertIn("terminada: 0 commit(s), 0 usos de herramientas", self.read(b, "execution", "run_log.md"))
        self.hook("session-end", {"cwd": a}, a)
        self.assertIn("terminada: 0 commit(s), 1 usos de herramientas", self.read(a, "execution", "run_log.md"))
        self.assertEqual(os.listdir(self.sessions), [])

    def test_stop_sin_commits_es_silencioso_y_actualiza_estado(self):
        project = self.new_project()
        self.hook("session-start", self.payload(project), project)
        self.write(os.path.join(project, "tasks", "backlog.md"), "# Pendientes\n- [ ] T-001 [P1] editada a mano (creada 2026-01-01)\n")
        result = self.hook("stop", self.payload(project), project)
        self.assertEqual(result.stdout, "")
        self.assertIn("1 pendientes", self.read(project, "state.md"))

    def test_session_end_resume_sesion(self):
        project = self.new_project()
        self.hook("session-start", self.payload(project), project)
        for tool in ("Bash", "Bash", "Edit", "Read"):
            self.hook("post-tool", self.payload(project, tool_name=tool, tool_input={}), project)
        self.hook("session-end", self.payload(project, reason="clear"), project)
        run_log = self.read(project, "execution", "run_log.md")
        self.assertIn("[sesión] terminada: 0 commit(s), 4 usos de herramientas (clear)", run_log)
        usage = self.read(project, "tools", "tool_usage.md")
        self.assertRegex(usage, r"- \d{4}-\d{2}-\d{2} \| s1 \| Bash×2, Edit×1, Read×1\n")
        state = json.loads(self.read(project, "tools", "tool_state.json"))
        self.assertEqual(state["ultima_sesion"]["herramientas"], {"Bash": 2, "Edit": 1, "Read": 1})
        month = self.read(self.ws, "logs", "current_month.md")
        self.assertIn("demo — terminada: 0 commit(s), 4 usos de herramientas (clear)", month)
        self.assertRegex(month, r"^# Registro de \d{4}-\d{2}\n")
        self.assertEqual(os.listdir(self.sessions), [])

    def test_session_end_sigue_si_tool_state_no_es_un_objeto(self):
        project = self.new_project()
        self.write(os.path.join(project, "tools", "tool_state.json"), "[]")
        self.hook("session-start", self.payload(project), project)
        self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={}), project)
        self.hook("session-end", self.payload(project, reason="clear"), project)
        self.assertIn("demo — terminada", self.read(self.ws, "logs", "current_month.md"))
        self.assertEqual(os.listdir(self.sessions), [])
        self.assertEqual(self.read(project, "tools", "tool_state.json"), "[]")

    def test_session_end_un_paso_que_falla_no_impide_los_demas(self):
        project = self.new_project()
        usage = os.path.join(project, "tools", "tool_usage.md")
        os.remove(usage)
        os.makedirs(usage)  # el paso de herramientas no puede escribir aquí
        self.hook("session-start", self.payload(project), project)
        self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={}), project)
        self.hook("session-end", self.payload(project), project)
        self.assertIn("[sesión] terminada", self.read(project, "execution", "run_log.md"))
        self.assertIn("demo — terminada", self.read(self.ws, "logs", "current_month.md"))
        self.assertIn("session-end (herramientas)", self.read(self.ws, "logs", "debug.md"))
        self.assertEqual(os.listdir(self.sessions), [])

    def test_session_end_rota_el_log_mensual(self):
        project = self.new_project()
        self.write(os.path.join(self.ws, "logs", "current_month.md"), "# Registro de 2020-01\n\n- viejo\n")
        self.hook("session-end", self.payload(project), project)
        self.assertIn("- viejo", self.read(self.ws, "logs", "2020-01.md"))
        current = self.read(self.ws, "logs", "current_month.md")
        self.assertNotIn("viejo", current)
        self.assertIn("demo — terminada", current)

    def test_log_mensual_con_texto_ajeno_no_se_rota(self):
        project = self.new_project()
        self.write(os.path.join(self.ws, "logs", "current_month.md"), "notas mías\n")
        self.hook("session-end", self.payload(project), project)
        current = self.read(self.ws, "logs", "current_month.md")
        self.assertTrue(current.startswith("notas mías\n"))
        self.assertIn("demo — terminada", current)
        self.assertEqual(sorted(os.listdir(os.path.join(self.ws, "logs"))), ["current_month.md", "debug.md"])

    def test_errores_internos_van_a_debug_y_no_rompen(self):
        project = self.new_project()
        self.write(os.path.join(project, "tools", "tool_state.json"), "{ esto no es json")
        self.hook("post-tool", self.payload(project, tool_name="Bash", tool_input={}), project)
        result = self.hook("session-end", self.payload(project), project)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.read(project, "tools", "tool_state.json"), "{ esto no es json")


class TestSync(AwCase):
    def legacy_project(self, name="viejo"):
        """Proyecto como los creados antes de este cambio: archivos vacíos y sin skills/, CLAUDE.md ni .claude/."""
        self.init()
        project = self.project(name)
        for rel in ("tasks/backlog.md", "tasks/active.md", "tasks/done.md", "execution/run_log.md", "execution/decisions.md",
                    "execution/errors.md", "agents/assigned_agents.md", "agents/agent_context.md", "tools/tool_usage.md",
                    "artifacts/outputs.md", "artifacts/code_snippets.md", "artifacts/assets_index.md", "sop/workflow.md",
                    "sop/rules.md", "sop/conventions.md", "sop/README.md", "memory.md"):
            self.write(os.path.join(project, rel), "")
        self.write(os.path.join(project, "tools", "tool_state.json"), "")
        self.write(os.path.join(project, "context_index.json"), "")
        self.write(os.path.join(project, "project.md"), "# viejo\n\nMi descripción original\n")
        self.write(os.path.join(project, "state.md"), "Estado: iniciado\n")
        return project

    def test_dry_run_no_cambia_nada(self):
        project = self.legacy_project()
        snapshot = self.snapshot(project)
        result = self.aw("sync", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Modo prueba", result.stdout)
        self.assertIn("crear: skills/assigned_skills.md", result.stdout)
        self.assertIn("crear: CLAUDE.md", result.stdout)
        self.assertIn("crear: .claude/settings.json", result.stdout)
        self.assertIn("rellenar: tasks/backlog.md", result.stdout)
        self.assertEqual(self.snapshot(project), snapshot)

    def snapshot(self, project):
        data = {}
        for dirpath, _dirs, files in os.walk(project):
            for fname in files:
                path = os.path.join(dirpath, fname)
                data[os.path.relpath(path, project)] = slurp(path)
        return data

    def test_sync_completa_un_proyecto_antiguo_sin_pisar_lo_suyo(self):
        project = self.legacy_project()
        self.write(os.path.join(project, "sop", "rules.md"), "mis reglas propias\n")
        result = self.aw("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mi descripción original", self.read(project, "project.md"))
        self.assertEqual(self.read(project, "sop", "rules.md"), "mis reglas propias\n")
        for rel in ("skills/assigned_skills.md", "skills/skill_context.md", "tools/assigned_tools.md", "CLAUDE.md", ".claude/settings.json"):
            self.assertTrue(os.path.isfile(os.path.join(project, rel)), rel)
        for dirpath, _dirs, files in os.walk(project):
            for fname in files:
                self.assertGreater(os.path.getsize(os.path.join(dirpath, fname)), 0, fname)
        self.assertIn("CLAUDE.md — viejo", self.read(project, "CLAUDE.md"))
        self.assertNotIn("@@", self.read(project, "CLAUDE.md"))
        self.assertTrue(self.read(project, "state.md").startswith("Estado: 0 en curso"))
        index = json.loads(self.read(project, "context_index.json"))
        self.assertIn("project.md", index["archivos"])
        self.assertEqual(index["proyecto"], "viejo")

    def test_sync_es_idempotente(self):
        self.legacy_project()
        self.aw("sync")
        second = self.aw("sync")
        self.assertIn("- viejo: al día", second.stdout)
        self.assertIn("Total: 0 cambio(s)", second.stdout)
        self.assertEqual([f for f in os.listdir(os.path.join(self.project("viejo"), ".claude")) if ".bak-" in f], [])

    def test_sync_no_toca_claude_md_existente_ni_state_manual(self):
        project = self.legacy_project()
        self.write(os.path.join(project, "CLAUDE.md"), "el mío\n")
        self.write(os.path.join(project, "state.md"), "Estado: escrito a mano\n")
        self.aw("sync")
        self.assertEqual(self.read(project, "CLAUDE.md"), "el mío\n")
        self.assertEqual(self.read(project, "state.md"), "Estado: escrito a mano\n")

    def test_sync_fusiona_settings_sin_perder_nada_y_con_respaldo(self):
        project = self.legacy_project()
        custom = {
            "permissions": {"allow": ["Bash(ls)"], "deny": ["Read(./.env)"]},
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mi-freno.sh"}]}],
                "SessionStart": [{"hooks": [{"type": "command", "command": "mi-inicio.sh"}]}],
            },
            "outputStyle": "Concise",
        }
        path = os.path.join(project, ".claude", "settings.json")
        self.write(path, json.dumps(custom))
        result = self.aw("sync")
        self.assertIn("actualizar: .claude/settings.json", result.stdout)
        merged = json.loads(slurp(path))
        self.assertEqual(merged["outputStyle"], "Concise")
        self.assertEqual(merged["permissions"]["deny"], ["Read(./.env)"])
        self.assertEqual(merged["permissions"]["allow"][0], "Bash(ls)")
        self.assertIn("Bash(aw task *)", merged["permissions"]["allow"])
        self.assertEqual(merged["hooks"]["PreToolUse"], custom["hooks"]["PreToolUse"])
        commands = [h["command"] for g in merged["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertEqual(commands[0], "mi-inicio.sh")
        self.assertTrue(any("hook session-start" in c for c in commands))
        for event in HOOK_EVENTS:
            self.assertIn(event, merged["hooks"])
        backups = [f for f in os.listdir(os.path.dirname(path)) if ".bak-" in f]
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(slurp(os.path.join(os.path.dirname(path), backups[0]))), custom)
        again = self.aw("sync")
        self.assertIn("al día", again.stdout)
        self.assertEqual(len([f for f in os.listdir(os.path.dirname(path)) if ".bak-" in f]), 1)

    def test_sync_repara_hooks_de_aw_desactualizados_sin_tocar_los_del_usuario(self):
        project = self.legacy_project()
        custom = {"hooks": {
            "PostToolUse": [{"hooks": [
                {"type": "command", "command": 'python3 "/viejo/generate.py" hook post-tool', "timeout": 5, "async": True},
                {"type": "command", "command": "mi-tool hook post-tool", "timeout": 3},
            ]}],
            "Stop": [{"hooks": [{"type": "command", "command": "otra-tool hook stop"}]}],
        }}
        path = os.path.join(project, ".claude", "settings.json")
        self.write(path, json.dumps(custom))
        result = self.aw("sync")
        self.assertIn("hook PostToolUse actualizado", result.stdout)
        merged = json.loads(slurp(path))
        mine, theirs = merged["hooks"]["PostToolUse"][0]["hooks"]
        self.assertIn(SCRIPT, mine["command"])
        self.assertTrue(mine["command"].endswith(" hook post-tool"))
        self.assertEqual(mine["timeout"], 10)
        self.assertNotIn("async", mine)
        self.assertEqual(theirs, {"type": "command", "command": "mi-tool hook post-tool", "timeout": 3})
        stop = [h["command"] for g in merged["hooks"]["Stop"] for h in g["hooks"]]
        self.assertEqual(stop[0], "otra-tool hook stop")
        self.assertTrue(any("generate.py" in c and c.endswith(" hook stop") for c in stop[1:]))
        self.assertIn("al día", self.aw("sync").stdout)

    def test_sync_no_duplica_hooks_ya_instalados(self):
        project = self.new_project()
        path = os.path.join(project, ".claude", "settings.json")
        before = slurp(path)
        self.aw("sync")
        self.assertEqual(slurp(path), before)

    def test_sync_con_settings_invalido_no_lo_toca(self):
        project = self.legacy_project()
        path = os.path.join(project, ".claude", "settings.json")
        self.write(path, "{ roto")
        result = self.aw("sync")
        self.assertIn("JSON inválido", result.stdout)
        self.assertEqual(slurp(path), "{ roto")

    def test_sync_indices_de_artifacts(self):
        project = self.new_project()
        self.write(os.path.join(project, "artifacts", "informe.html"), "<html></html>")
        self.write(os.path.join(project, "artifacts", "img", "logo.png"), "x")
        self.write(os.path.join(project, "artifacts", "outputs.md"), "# Entregables\nmi nota\n\n<!-- aw:auto:inicio -->\nviejo\n<!-- aw:auto:fin -->\n")
        self.aw("sync")
        outputs = self.read(project, "artifacts", "outputs.md")
        self.assertIn("mi nota", outputs)
        self.assertIn("- `artifacts/informe.html`", outputs)
        self.assertNotIn("viejo", outputs)
        self.assertNotIn("logo.png", outputs)
        assets = self.read(project, "artifacts", "assets_index.md")
        self.assertIn("- `artifacts/img/logo.png`", assets)
        self.assertNotIn("informe.html", assets)

    def test_sync_de_un_solo_proyecto_y_nombre_inexistente(self):
        self.legacy_project("a")
        self.write(os.path.join(self.project("b"), "state.md"), "Estado: iniciado\n")
        os.makedirs(os.path.join(self.project("b"), "tasks"))
        result = self.aw("sync", "a", "nada")
        self.assertIn("- a:", result.stdout)
        self.assertIn("- nada: no existe", result.stdout)
        self.assertNotIn("- b:", result.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.project("b"), "CLAUDE.md")))

    def test_sync_rechaza_nombres_invalidos_sin_tocar_nada(self):
        self.init()
        shutil.rmtree(os.path.join(self.ws, "core"))
        before = sorted(os.listdir(self.tmp))
        for name in ("../..", "..", ".oculto", "a/b", ""):
            result = self.aw("sync", name)
            self.assertEqual(result.returncode, 2, name)
            self.assertIn("Nombre de proyecto inválido", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "core")), "build() no debe correr con nombres inválidos")
        self.assertEqual(sorted(os.listdir(self.tmp)), before)

    def test_sync_actualiza_la_plantilla_del_workspace(self):
        self.init()
        template = os.path.join(self.ws, "projects", "template_project", "skills")
        shutil.rmtree(template)
        self.aw("sync")
        self.assertTrue(os.path.isfile(os.path.join(template, "assigned_skills.md")))


class TestDoctor(AwCase):
    def test_proyecto_nuevo_sin_pendientes_graves(self):
        self.new_project()
        result = self.aw("doctor")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("✓ hooks de aw instalados", result.stdout)
        self.assertIn("✓ estructura completa", result.stdout)
        self.assertIn("campo(s) '(completar)' por rellenar", result.stdout)
        self.assertIn("✓ state.md al día", result.stdout)
        self.assertNotIn("✕", result.stdout)

    def test_detecta_hooks_ausentes_json_roto_y_script_inexistente(self):
        project = self.new_project()
        path = os.path.join(project, ".claude", "settings.json")
        settings = json.loads(slurp(path))
        del settings["hooks"]["Stop"]
        self.write(path, json.dumps(settings))
        result = self.aw("doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("✕ faltan hooks: stop", result.stdout)
        settings = json.loads(slurp(path))
        settings["hooks"]["SessionStart"][0]["hooks"][0]["command"] = 'python3 "/no/existe/generate.py" hook session-start'
        self.write(path, json.dumps(settings))
        self.assertIn("apunta a un script que no existe", self.aw("doctor").stdout)
        self.write(path, "{ roto")
        self.assertIn("JSON inválido", self.aw("doctor").stdout)
        os.remove(path)
        self.assertIn("✕ .claude/settings.json no existe", self.aw("doctor").stdout)

    def test_detecta_estado_manual_y_permisos_faltantes(self):
        project = self.new_project()
        self.write(os.path.join(project, "state.md"), "Estado: a mano\n")
        path = os.path.join(project, ".claude", "settings.json")
        settings = json.loads(slurp(path))
        settings["permissions"]["allow"] = []
        self.write(path, json.dumps(settings))
        out = self.aw("doctor").stdout
        self.assertIn("▲ state.md tiene texto manual", out)
        self.assertIn("▲ faltan permisos", out)

    def test_compara_agentes_y_skills_asignados_con_el_disco(self):
        project = self.new_project()
        self.write(os.path.join(project, "agents", "assigned_agents.md"),
                   "# Agentes\n\n| Tarea | Agente (archivo) | Notas |\n|---|---|---|\n| Redacción | 2_agente_redactor.md | |\n| Otra | (completar) | |\n")
        self.write(os.path.join(project, "skills", "assigned_skills.md"),
                   "# Skills\n\n| Tarea | Skill | Notas |\n|---|---|---|\n| Auditar | auditor-de-procesos.skill | |\n")
        result = self.aw("doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("✕ agentes asignados: no existe 2_agente_redactor.md (fila 'Redacción')", result.stdout)
        self.assertIn("✕ skills asignados: no existe auditor-de-procesos.skill", result.stdout)
        self.write(os.path.join(self.ws, "agents", "2_agente_redactor.md"), "instrucciones")
        os.makedirs(os.path.join(self.ws, "skills", "auditor-de-procesos.skill"))
        result = self.aw("doctor")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("asignados", result.stdout)

    def test_compara_herramientas_con_mcp_json(self):
        project = self.new_project()
        self.write(os.path.join(project, "tools", "assigned_tools.md"),
                   "# Herramientas\n\n| Herramienta | Uso | Config |\n|---|---|---|\n| Airtable | tablas | .mcp.json |\n| Bash | comandos | nativa |\n")
        self.assertIn("herramienta 'Airtable' declarada en .mcp.json pero no figura ahí", self.aw("doctor").stdout)
        self.write(os.path.join(project, ".mcp.json"), json.dumps({"mcpServers": {"airtable": {}}}))
        self.assertNotIn("Airtable", self.aw("doctor").stdout)

    def test_detecta_commits_sin_decisiones_y_archivos_vacios(self):
        project = self.new_project()
        aw = load_aw(self.ws)
        for i in range(3):
            aw.log_event(project, "commit", f"abc{i} algo")
        self.write(os.path.join(project, "sop", "rules.md"), "")
        out = self.aw("doctor").stdout
        self.assertIn("3 commit(s) registrados y ninguna decisión", out)
        self.assertIn("1 archivo(s) vacío(s)", out)

    def test_cuenta_los_campos_pendientes_de_core_y_memory(self):
        self.new_project()
        out = self.aw("doctor").stdout
        self.assertRegex(out, r"▲ \d+ campo\(s\) '\(completar\)' por rellenar en core/ y memory/")
        for folder in ("core", "memory"):
            base = os.path.join(self.ws, folder)
            for fname in os.listdir(base):
                path = os.path.join(base, fname)
                if fname.endswith(".md"):
                    self.write(path, slurp(path).replace("(completar)", "listo"))
        self.assertIn("✓ core/ y memory/ sin campos pendientes", self.aw("doctor").stdout)

    def test_doctor_de_un_proyecto_y_proyecto_inexistente(self):
        self.new_project("uno")
        self.aw("project", "new", "dos")
        out = self.aw("doctor", "uno").stdout
        self.assertIn("Proyecto uno", out)
        self.assertNotIn("Proyecto dos", out)
        missing = self.aw("doctor", "nada")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("✕ no existe", missing.stdout)

    def test_doctor_rechaza_nombres_invalidos(self):
        self.new_project("uno")
        for name in ("../..", "..", ".oculto", "a/b", ""):
            result = self.aw("doctor", name)
            self.assertEqual(result.returncode, 2, name)
            self.assertIn("Nombre de proyecto inválido", result.stderr)
            self.assertNotIn("Proyecto", result.stdout)


class TestIndiceDelWorkspace(AwCase):
    def index(self):
        return json.loads(self.read(self.ws, "memory", "context_index.json"))

    def table(self):
        return self.read(self.ws, "memory", "projects", "project_index.md")

    def test_las_plantillas_del_indice_traen_formato(self):
        self.init()
        self.assertIn("| (ninguno todavía) |", self.table())
        self.assertEqual(self.index()["proyectos"], {})

    def test_crear_proyectos_los_agrega_al_indice(self):
        self.new_project("uno")
        self.aw("project", "new", "dos")
        index = self.index()
        self.assertEqual(sorted(index["proyectos"]), ["dos", "uno"])
        self.assertEqual(index["proyectos"]["uno"]["en_curso"], 0)
        self.assertRegex(index["proyectos"]["uno"]["ultima_actividad"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertIn("| uno | Estado: 0 en curso", self.table())
        self.assertIn("| dos |", self.table())
        self.assertNotIn("(ninguno todavía)", self.table())

    def test_el_cierre_de_sesion_actualiza_el_indice(self):
        project = self.new_project()
        self.aw("task", "add", "a", cwd=project)
        self.aw("task", "start", "T-001", cwd=project)
        self.hook("session-end", {"session_id": "i1", "cwd": project}, project)
        info = self.index()["proyectos"]["demo"]
        self.assertEqual((info["en_curso"], info["pendientes"]), (1, 0))
        self.assertIn("Estado: 1 en curso", self.table())

    def test_respeta_texto_propio_y_no_toca_json_roto(self):
        self.new_project()
        path = os.path.join(self.ws, "memory", "projects", "project_index.md")
        self.write(path, self.table() + "\nmi nota propia\n")
        self.write(os.path.join(self.ws, "memory", "context_index.json"), "{ roto")
        self.aw("project", "new", "otro")
        self.assertIn("mi nota propia", self.table())
        self.assertIn("| otro |", self.table())
        self.assertEqual(self.read(self.ws, "memory", "context_index.json"), "{ roto")
        self.assertIn("memory/context_index.json es inválido", self.aw("doctor").stdout)

    def test_barra_vertical_en_el_estado_no_rompe_la_tabla(self):
        project = self.new_project()
        self.write(os.path.join(project, "state.md"), "Estado: a | b\n")
        self.hook("session-end", {"session_id": "i2", "cwd": project}, project)
        self.assertIn("| demo | Estado: a / b |", self.table())

    def test_sync_agrega_proyectos_antiguos_y_el_doctor_lo_confirma(self):
        self.init()
        self.write(os.path.join(self.project("viejo"), "state.md"), "Estado: iniciado\n")
        os.makedirs(os.path.join(self.project("viejo"), "tasks"))
        self.assertIn("no incluye 1 proyecto(s)", self.aw("doctor").stdout)
        self.aw("sync")
        self.assertIn("viejo", self.index()["proyectos"])
        self.assertIn("| viejo |", self.table())
        self.assertIn("✓ índice de proyectos al día", self.aw("doctor").stdout)


class TestClaudeMdDelWorkspace(AwCase):
    def setUp(self):
        super().setUp()
        self.tpl = os.path.join(self.tmp, "tpl")
        shutil.copytree(os.path.join(REPO, "templates"), self.tpl)

    def awt(self, *args):
        env = dict(self.env, AW_TEMPLATES=self.tpl)
        return subprocess.run([sys.executable, SCRIPT, *args], cwd=self.tmp, env=env, capture_output=True, text=True)

    def path(self):
        return os.path.join(self.ws, "CLAUDE.md")

    def backups(self):
        return [f for f in os.listdir(self.ws) if f.startswith("CLAUDE.md.bak-")]

    def edit_template(self, extra):
        with open(os.path.join(self.tpl, "CLAUDE.md"), "a", encoding="utf-8") as f:
            f.write(extra)

    def test_lleva_huella_valida(self):
        self.awt("init")
        text = slurp(self.path())
        match = re.search(r"<!-- aw:plantilla sha256=([0-9a-f]{64}) -->\n\Z", text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), hashlib.sha256(text[:match.start()].encode("utf-8")).hexdigest())
        self.assertNotIn("@@", text)

    def test_se_actualiza_sola_si_nadie_la_modifico(self):
        self.awt("init")
        self.edit_template("\n## Sección nueva\n")
        out = self.awt("sync").stdout
        self.assertIn("workspace: CLAUDE.md: plantilla nueva aplicada", out)
        self.assertIn("## Sección nueva", slurp(self.path()))
        self.assertEqual(len(self.backups()), 1)
        self.assertNotIn("Sección nueva", slurp(os.path.join(self.ws, self.backups()[0])))
        again = self.awt("sync").stdout
        self.assertNotIn("workspace: CLAUDE.md", again)
        self.assertEqual(len(self.backups()), 1)

    def test_init_tambien_la_actualiza_si_no_fue_modificada(self):
        self.awt("init")
        self.edit_template("\n## Otra sección\n")
        self.assertIn("plantilla nueva aplicada", self.awt("init").stdout)
        self.assertIn("## Otra sección", slurp(self.path()))

    def test_no_pisa_cambios_propios_salvo_con_workspace(self):
        self.awt("init")
        edited = slurp(self.path()).replace("## Límites", "## Mis límites")
        self.assertIn("## Mis límites", edited)
        self.write(self.path(), edited)
        self.edit_template("\nnuevo\n")
        out = self.awt("sync").stdout
        self.assertIn("difiere de la plantilla", out)
        self.assertIn("aw sync --workspace", out)
        self.assertIn("## Mis límites", slurp(self.path()))
        self.assertEqual(self.backups(), [])
        self.assertIn("difiere de la plantilla", self.awt("init").stdout)
        dry = self.awt("sync", "--workspace", "--dry-run").stdout
        self.assertIn("se aplicaría la plantilla nueva", dry)
        self.assertIn("## Mis límites", slurp(self.path()))
        self.assertEqual(self.backups(), [])
        self.assertIn("plantilla nueva aplicada", self.awt("sync", "--workspace").stdout)
        self.assertIn("nuevo", slurp(self.path()))
        self.assertNotIn("Mis límites", slurp(self.path()))
        self.assertIn("## Mis límites", slurp(os.path.join(self.ws, self.backups()[0])))

    def test_version_anterior_sin_huella(self):
        self.awt("init")
        current = slurp(self.path())
        # Igual a la plantilla pero sin huella: solo se le añade la huella.
        self.write(self.path(), re.sub(r"<!-- aw:plantilla.*?-->\n", "", current))
        self.assertIn("se le añadió la huella", self.awt("sync").stdout)
        self.assertEqual(slurp(self.path()), current)
        # Versión distinta y sin huella (la creada antes de existir este mecanismo): no se pisa sola.
        self.write(self.path(), "# Protocolo aw (workspace)\nversión anterior\n")
        self.assertIn("difiere de la plantilla", self.awt("sync").stdout)
        self.assertEqual(slurp(self.path()), "# Protocolo aw (workspace)\nversión anterior\n")
        self.assertIn("plantilla nueva aplicada", self.awt("sync", "--workspace").stdout)
        self.assertEqual(slurp(self.path()), current)
        self.assertEqual(len(self.backups()), 1)

    def test_archivo_vacio_se_rellena(self):
        self.awt("init")
        self.write(self.path(), "")
        self.awt("init")
        self.assertIn("Protocolo aw", slurp(self.path()))

    def test_un_claude_md_ajeno_no_se_toca_ni_con_workspace(self):
        self.awt("init")
        own = "# CLAUDE.md\n\nInstrucciones propias de este repo\n"
        self.write(self.path(), own)
        for args in (("sync",), ("sync", "--workspace"), ("init",)):
            out = self.awt(*args).stdout
            self.assertIn("no es el del workspace aw", out, args)
            self.assertIn("aw init", out, args)  # dice cómo recuperarse si era una versión antigua
            self.assertEqual(slurp(self.path()), own, args)
        self.assertEqual(self.backups(), [])
        self.assertIn("aw no lo gestiona", self.awt("doctor").stdout)
        os.rename(self.path(), self.path() + ".antiguo")  # lo que dicen los avisos: renombrarlo y ejecutar aw init
        self.awt("init")
        self.assertTrue(slurp(self.path()).startswith("# Protocolo aw (workspace)"))
        self.assertEqual(slurp(self.path() + ".antiguo"), own)

    def test_con_huella_sigue_siendo_del_workspace_aunque_cambie_la_primera_linea(self):
        self.awt("init")
        edited = slurp(self.path()).replace("# Protocolo aw (workspace)", "# Mi protocolo", 1)
        self.write(self.path(), edited)
        out = self.awt("sync").stdout
        self.assertIn("difiere de la plantilla", out)
        self.assertNotIn("no es el del workspace aw", out)
        self.assertEqual(slurp(self.path()), edited)
        self.assertIn("plantilla nueva aplicada", self.awt("sync", "--workspace").stdout)

    def test_el_doctor_avisa_si_esta_desactualizada(self):
        self.awt("init")
        self.awt("project", "new", "x")
        self.assertNotIn("el CLAUDE.md del workspace difiere", self.awt("doctor").stdout)
        self.edit_template("\nnuevo\n")
        self.assertIn("el CLAUDE.md del workspace difiere de la plantilla", self.awt("doctor").stdout)
        self.awt("sync")
        self.assertNotIn("el CLAUDE.md del workspace difiere", self.awt("doctor").stdout)


class TestSettingsDesdeLaPlantilla(AwCase):
    def dirs(self, path):
        return json.loads(slurp(path))["permissions"]["additionalDirectories"]

    def strip_new_dirs(self, path):
        settings = json.loads(slurp(path))
        settings["permissions"]["additionalDirectories"] = [
            d for d in settings["permissions"]["additionalDirectories"] if not d.endswith(("/core", "/memory"))]
        self.write(path, json.dumps(settings))

    def test_sync_lleva_lo_nuevo_a_proyectos_y_a_la_plantilla(self):
        project = self.new_project()
        template = os.path.join(self.ws, "projects", "template_project")
        paths = [os.path.join(project, ".claude", "settings.json"), os.path.join(template, ".claude", "settings.json")]
        for path in paths:
            self.strip_new_dirs(path)
            self.assertEqual(len(self.dirs(path)), 3)
        out = self.aw("sync").stdout
        self.assertIn("- plantilla: actualizar: .claude/settings.json", out)
        self.assertIn("- demo: 1 cambio(s)", out)
        for path in paths:
            self.assertEqual(self.dirs(path)[-2:], [os.path.join(self.ws, "core"), os.path.join(self.ws, "memory")])
            self.assertEqual(len([f for f in os.listdir(os.path.dirname(path)) if ".bak-" in f]), 1)
        second = self.aw("sync").stdout
        self.assertNotIn("- plantilla:", second)
        self.assertIn("Total: 0 cambio(s)", second)

    def test_los_respaldos_de_la_plantilla_no_llegan_a_proyectos_nuevos(self):
        self.new_project()
        template = os.path.join(self.ws, "projects", "template_project", ".claude", "settings.json")
        self.strip_new_dirs(template)
        self.aw("sync")
        self.assertEqual(len([f for f in os.listdir(os.path.dirname(template)) if ".bak-" in f]), 1)
        self.aw("project", "new", "nuevo")
        self.assertEqual([f for f in os.listdir(os.path.join(self.project("nuevo"), ".claude")) if ".bak-" in f], [])
        out = self.aw("doctor", "nuevo").stdout
        self.assertNotIn("faltan", out)
        self.assertNotIn("✕", out)


class Corte(Exception):
    """Simula que el proceso se corta a mitad de una operación."""


HOLD_LOCK = ("import fcntl, os, sys\n"
             "fd = os.open(sys.argv[1], os.O_RDONLY)\n"
             "fcntl.flock(fd, fcntl.LOCK_EX)\n"
             "print('listo', flush=True)\n"
             "sys.stdin.read()\n")


class TestBloqueoYAtomicidad(AwCase):
    def setUp(self):
        super().setUp()
        self.aw_mod = load_aw(self.ws)

    def ids(self, project, name):
        return [t["id"] for t in self.aw_mod.load_tasks(project, name)]

    def cut_on_write(self, nth):
        """Hace que la escritura número nth de write_text falle. Devuelve la función que restaura el original."""
        mod, original, calls = self.aw_mod, self.aw_mod.write_text, []

        def fake(path, text):
            calls.append(path)
            if len(calls) == nth:
                raise Corte()
            original(path, text)

        mod.write_text = fake
        restore = lambda: setattr(mod, "write_text", original)
        self.addCleanup(restore)
        return restore

    def test_task_start_no_pierde_la_tarea_si_se_corta_a_mitad(self):
        project = self.new_project()
        self.aw_mod.task_add(project, "hacer algo", "P1")
        self.cut_on_write(2)
        with self.assertRaises(Corte):
            self.aw_mod.task_start(project, "T-001")
        self.assertIn("T-001", self.ids(project, "backlog.md") + self.ids(project, "active.md"))

    def test_task_start_reintentado_tras_un_corte_completa_el_movimiento(self):
        project = self.new_project()
        self.aw_mod.task_add(project, "hacer algo", "P1")
        restore = self.cut_on_write(2)
        with self.assertRaises(Corte):
            self.aw_mod.task_start(project, "T-001")
        restore()
        self.aw_mod.task_start(project, "T-001")
        self.assertEqual(self.ids(project, "backlog.md"), [])
        self.assertEqual(self.ids(project, "active.md"), ["T-001"])
        with self.assertRaises(self.aw_mod.AwError):  # sin copia pendiente sigue siendo un error
            self.aw_mod.task_start(project, "T-001")

    def test_task_done_no_pierde_la_tarea_si_se_corta_al_guardar(self):
        project = self.new_project()
        self.aw_mod.task_add(project, "hacer algo")
        self.aw_mod.task_start(project, "T-001")

        def fail(path, text):
            raise Corte()

        original = self.aw_mod.append_text
        self.aw_mod.append_text = fail
        self.addCleanup(setattr, self.aw_mod, "append_text", original)
        with self.assertRaises(Corte):
            self.aw_mod.task_done(project, "T-001")
        self.assertIn("T-001", self.ids(project, "active.md") + self.ids(project, "done.md"))

    def test_task_done_reintentado_tras_un_corte_no_duplica(self):
        project = self.new_project()
        self.aw_mod.task_add(project, "hacer algo")
        self.aw_mod.task_start(project, "T-001")
        restore = self.cut_on_write(1)
        with self.assertRaises(Corte):
            self.aw_mod.task_done(project, "T-001")
        restore()
        self.assertEqual(self.ids(project, "done.md"), ["T-001"])
        self.assertEqual(self.ids(project, "active.md"), ["T-001"])  # duplicada por el corte, no perdida
        self.aw_mod.task_done(project, "T-001")
        self.assertEqual(self.ids(project, "done.md"), ["T-001"])
        self.assertEqual(self.ids(project, "active.md"), [])

    def test_task_add_espera_si_el_proyecto_esta_bloqueado(self):
        project = self.new_project()
        with self.aw_mod.project_lock(project):
            proc = subprocess.Popen([sys.executable, SCRIPT, "task", "add", "espera"], cwd=project, env=self.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.addCleanup(proc.kill)
            time.sleep(0.7)
            self.assertIsNone(proc.poll(), "task add no debe terminar mientras el proyecto está bloqueado")
        _out, err = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, err)
        self.assertIn("espera", self.read(project, "tasks", "backlog.md"))

    def test_task_add_en_paralelo_no_repite_identificadores(self):
        project = self.new_project()
        procs = [subprocess.Popen([sys.executable, SCRIPT, "task", "add", f"tarea {i}"], cwd=project, env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(8)]
        for proc in procs:
            _out, err = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(sorted(self.ids(project, "backlog.md")), [f"T-{i:03d}" for i in range(1, 9)])

    def test_project_lock_es_reentrante(self):
        project = self.new_project()
        self.aw_mod.LOCK_TIMEOUT = 0.3  # si no fuera reentrante, fallaría en 0,3 s en vez de colgarse
        with self.aw_mod.project_lock(project):
            self.aw_mod.task_add(project, "dentro del bloqueo")
            self.aw_mod.decide(project, "algo", "porque")
            with self.aw_mod.project_lock(project):
                pass
        self.assertEqual(self.ids(project, "backlog.md"), ["T-001"])

    def test_project_lock_da_error_si_otro_proceso_lo_retiene(self):
        project = self.new_project()
        holder = subprocess.Popen([sys.executable, "-c", HOLD_LOCK, project], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.kill)
        self.addCleanup(holder.stdout.close)
        self.assertEqual(holder.stdout.readline().strip(), "listo")
        self.aw_mod.LOCK_TIMEOUT = 0.3
        with self.assertRaises(self.aw_mod.AwError):
            with self.aw_mod.project_lock(project):
                pass
        holder.stdin.close()
        holder.wait(timeout=10)
        with self.aw_mod.project_lock(project):  # al liberarse el otro proceso ya se puede
            pass


class TestFunciones(AwCase):
    def setUp(self):
        super().setUp()
        self.aw_mod = load_aw(self.ws)

    def test_redact(self):
        r = self.aw_mod.redact
        self.assertNotIn("abc123", r("Authorization: Bearer abc123"))
        self.assertNotIn("hunter2", r("password=hunter2"))
        self.assertNotIn("supersecretvalue", r("api_key: supersecretvalue"))
        self.assertNotIn("ghp_" + "a" * 20, r("token ghp_" + "a" * 20))
        self.assertNotIn("A" * 40, r("clave " + "A" * 40))
        self.assertEqual(r("Could not resolve host"), "Could not resolve host")
        self.assertEqual(r("invalid token provided"), "invalid token provided")

    def test_redact_claves_con_prefijo_sufijo_o_comillas(self):
        r = self.aw_mod.redact
        for text, secret in (("DB_PASSWORD=hunter2", "hunter2"),
                             ("client_secret=abc987", "abc987"),
                             ("GITHUB_TOKEN: zzz111", "zzz111"),
                             ("AWS_ACCESS_KEY=k123", "k123"),
                             ("private-key=pk777", "pk777"),
                             ('{"password": "hunter two"}', "hunter two"),
                             ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
                             ('-H "Authorization: Bearer abc123"', "abc123")):
            self.assertNotIn(secret, r(text), text)

    def test_redact_credenciales_en_urls_y_consultas(self):
        r = self.aw_mod.redact
        clone = r("git clone https://usuario:s3cr3t@github.com/a/b.git")
        self.assertNotIn("s3cr3t", clone)
        self.assertIn("github.com/a/b.git", clone)
        query = r("GET /cb?code=1&access_token=abc999&page=2")
        self.assertNotIn("abc999", query)
        self.assertIn("page=2", query)
        self.assertNotIn("k9k9k9", r("https://api.x.io/v1?key=k9k9k9"))
        self.assertEqual(r("ssh://git@github.com/a/b.git"), "ssh://git@github.com/a/b.git")

    def test_redact_base64_con_barras_y_rutas_largas(self):
        r = self.aw_mod.redact
        key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        self.assertNotIn("K7MDENG", r("clave " + key))
        ruta = "/home/usuario/proyectos/agencia/informes/resumen_mensual"
        self.assertEqual(r("leyendo " + ruta), "leyendo " + ruta)

    def test_redact_no_oculta_de_mas(self):
        r = self.aw_mod.redact
        for text in ("authorization failed for user", "Could not resolve host", "the secret was rotated"):
            self.assertEqual(r(text), text)

    def test_clean_title(self):
        self.assertEqual(self.aw_mod.clean_title("hacer algo (creada 2026-01-01) (iniciada 2026-01-02)"), "hacer algo")
        self.assertEqual(self.aw_mod.clean_title("con (paréntesis) propios (creada 2026-01-01)"), "con (paréntesis) propios")

    def test_insert_task_line_ordena_y_conserva_encabezado(self):
        insert = self.aw_mod.insert_task_line
        text = "# Pendientes\n<!-- x -->\n- [ ] T-001 [P0] a\n- [ ] T-002 [P2] b\n"
        out = insert(text, "- [ ] T-003 [P1] c", "P1")
        self.assertEqual(out.splitlines(), ["# Pendientes", "<!-- x -->", "- [ ] T-001 [P0] a", "- [ ] T-003 [P1] c", "- [ ] T-002 [P2] b"])
        self.assertEqual(insert("", "- [ ] T-001 [P2] a", "P2"), "- [ ] T-001 [P2] a\n")

    def test_git_commit_regex(self):
        rx = self.aw_mod.GIT_COMMIT_RE
        for yes in ("git commit -m x", "git commit", "cd a && git commit -m y", "git -c user.name=a commit -m y",
                    "git --no-pager commit", "npm test; git commit -am z"):
            self.assertTrue(rx.search(yes), yes)
        for no in ("git log --grep commit", "echo git commit-tree", "git status", "git committer", "ls"):
            self.assertFalse(rx.search(no), no)

    def test_merge_settings_no_modifica_el_original(self):
        existing = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "otro.sh"}]}]}}
        template = {"permissions": {"allow": ["Bash(aw task *)"]},
                    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": 'python3 "x/generate.py" hook stop'}]}]}}
        merged, notes = self.aw_mod.merge_settings(existing, template)
        self.assertEqual(existing["permissions"]["allow"], ["Bash(ls)"])
        self.assertEqual(len(merged["hooks"]["Stop"]), 2)
        self.assertEqual(len(notes), 2)
        merged_again, notes_again = self.aw_mod.merge_settings(merged, template)
        self.assertEqual(notes_again, [])
        self.assertEqual(merged_again, merged)

    def test_state_is_auto_exige_la_linea_exacta_de_la_marca(self):
        auto, mark = self.aw_mod.state_is_auto, self.aw_mod.MARK_AUTO
        for text in ("", "  \n", "Estado: iniciado\n", f"Estado: x\n{mark}\n", f"Estado: x\r\n  {mark}  \r\n"):
            self.assertTrue(auto(text), repr(text))
        for text in ("Estado: a mano\n", "Estado: x\nver aw:auto\n", "<!-- aw:auto -->\n", f"Estado: x\n{mark} extra\n"):
            self.assertFalse(auto(text), repr(text))

    def test_build_digest_conserva_las_lineas_de_un_estado_manual(self):
        project = self.new_project()
        state = os.path.join(project, "state.md")
        self.write(state, "Estado: mío\nnota sobre aw:auto\n")
        self.assertIn("nota sobre aw:auto", self.aw_mod.build_digest(project))
        self.write(state, self.aw_mod.build_state(project))
        self.assertNotIn(self.aw_mod.MARK_AUTO, self.aw_mod.build_digest(project))

    def test_merge_settings_no_toma_un_hook_ajeno_por_uno_de_aw(self):
        existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "otra-tool hook stop"}]}]}}
        template = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": 'python3 "x/generate.py" hook stop', "timeout": 10}]}]}}
        merged, notes = self.aw_mod.merge_settings(existing, template)
        self.assertEqual(len(merged["hooks"]["Stop"]), 2)
        self.assertEqual(merged["hooks"]["Stop"][0], existing["hooks"]["Stop"][0])
        self.assertEqual(notes, ["hook Stop"])

    def test_merge_settings_actualiza_en_su_sitio_los_hooks_de_aw(self):
        old = {"type": "command", "command": 'python3 "/viejo/generate.py" hook stop', "timeout": 5, "async": True}
        new = {"type": "command", "command": 'python3 "x/generate.py" hook stop', "timeout": 10}
        existing = {"hooks": {"Stop": [{"hooks": [old]}]}}
        template = {"hooks": {"Stop": [{"hooks": [new]}]}}
        merged, notes = self.aw_mod.merge_settings(existing, template)
        self.assertEqual(merged["hooks"]["Stop"], [{"hooks": [new]}])
        self.assertEqual(notes, ["hook Stop actualizado"])
        self.assertTrue(existing["hooks"]["Stop"][0]["hooks"][0]["async"])  # el original no se modifica
        again, notes_again = self.aw_mod.merge_settings(merged, template)
        self.assertEqual(notes_again, [])
        self.assertEqual(again, merged)

    def test_render_json_escapa_comillas(self):
        rendered = self.aw_mod.render('{"c": "@@AW_CMD@@ hook x"}', {"AW_CMD": 'python3 "/a b/generate.py"'}, json_safe=True)
        self.assertEqual(json.loads(rendered)["c"], 'python3 "/a b/generate.py" hook x')
        self.assertEqual(self.aw_mod.render("@@DESCONOCIDA@@", {}), "@@DESCONOCIDA@@")


if __name__ == "__main__":
    unittest.main()
