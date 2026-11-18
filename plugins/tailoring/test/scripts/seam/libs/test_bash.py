"""seam/libs/bash.py 시험 — 작업 세션 Bash 판정(git 되돌리기·리드 저장소 쓰기·셸 가공·켜는 git 깃발·glob 뒤 `..`·deny 읽기·쓰기·인터프리터 본문·patch)."""
import os
import shutil
import tempfile
import unittest

from test import helpers as testing
from seam.libs import bash as g


LEAD = "/x/proj-alpha"  # GuardCases 밖 시험이 쓰는 리드 이름


def mock_limit(mod, n):
    from unittest import mock
    return mock.patch.object(mod, "WALK_LIMIT", n)


DIFF = "--- a/deny/s.json\n+++ b/deny/s.json\n@@ -0,0 +1 @@\n+x\n"


OK_DIFF = "--- a/x/q\n+++ b/x/q\n@@ -0,0 +1 @@\n+x\n"


class GuardCases:
    """리드 저장소 이름 LEAD 하나로 도는 git·셸 판정 시험."""
    LEAD = None

    def blocked(self, cmd):
        return g.reason(cmd, self.LEAD) is not None

    def test_blocks_reverting_git_in_any_form(self):
        for cmd in ("git checkout x", "git -C /tmp/w checkout x", "git -c a=b reset --hard", "/usr/bin/git stash",
                    "env A=1 git restore f", "command git switch m", "FOO=1 git clean -fd", "git --git-dir=/g stash pop",
                    "git push", "git worktree remove /w", "git branch -D b", "git branch -d b", "git branch --delete b",
                    "echo hi && git checkout x", "true; git stash", "ls | xargs git checkout",
                    "sh -c 'git checkout x'", "bash -lc \"git -C /w reset --hard\"", "zsh -c 'cd /w && git switch m'"):
            self.assertTrue(self.blocked(cmd), cmd)

    def test_allows_normal_work(self):
        for cmd in ("git status", "git -C /w log --oneline -3", "git commit -qam 'msg; git checkout x'", "git reset --soft HEAD~1",
                    "git branch --show-current", "git branch", "git diff --stat", "python3 x.py", "echo git checkout",
                    "grep -rn 'git stash' .", "git add -A .agents && git commit -qm m"):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_blocks_writes_to_lead_checkout_but_allows_reads(self):
        self.assertTrue(self.blocked(f"git -C {self.LEAD}/svc commit -m x"))
        self.assertTrue(self.blocked(f"git -C {self.LEAD} merge b"))
        self.assertFalse(self.blocked(f"git -C {self.LEAD} log --oneline"))
        self.assertFalse(self.blocked(f"git -C {self.LEAD}-P-099 commit -m x"))

    def test_blocks_lead_writes_in_every_path_form(self):
        for cmd in (f"git --git-dir {self.LEAD}/.git commit -m x", f"git --work-tree {self.LEAD} add .", f"git -C{self.LEAD} commit -m x",
                    f"git -C ../../../{os.path.basename(self.LEAD)} commit -m x", f"GIT_DIR={self.LEAD}/.git git commit -m x", f"git -C {self.LEAD} config user.name x",
                    f"git -C {self.LEAD} remote add o u", f"cd {self.LEAD} && git commit -m x", f"cd {self.LEAD}/svc; git merge b"):
            self.assertIsNotNone(g.reason(cmd, self.LEAD, cwd=f"{self.LEAD}-P-099/svc/x"), cmd)
        self.assertIsNotNone(g.reason("git commit -m x", self.LEAD, cwd=f"{self.LEAD}/svc"))
        self.assertIsNone(g.reason("git commit -m x", self.LEAD, cwd=f"{self.LEAD}-P-099/svc"))
        self.assertIsNone(g.reason(f"cd {self.LEAD} && git log -3", self.LEAD, cwd="/"))
        for cmd in (f"git -C {self.LEAD} config --get user.name", f"git -C {self.LEAD} remote -v", f"git -C {self.LEAD} branch --show-current"):
            self.assertIsNone(g.reason(cmd, self.LEAD), cmd)

    def test_blocks_more_ref_moves_and_indirection(self):
        for cmd in ("git reset --keep HEAD~1", "git reset --merge", "git branch -f main HEAD", "git branch -M a b",
                    "git update-ref -d refs/heads/x", "git -c alias.co=checkout co x", "eval git stash",
                    "git $(echo stash)", "git `echo stash`", "{ git stash; }", "if true; then git stash; fi",
                    "for f in a; do git checkout $f; done", "! git stash", "xargs -I {} git checkout {}", "nice -n 5 git stash",
                    "sudo -u x git stash", "timeout 5 git stash", "stdbuf -oL git stash", "echo `git stash`",
                    "echo $(git checkout x)", f"git -C {self.LEAD} config core.hooksPath /tmp"):
            self.assertTrue(self.blocked(cmd), cmd)

    def test_blocks_param_mangling_that_stalls_on_a_prompt(self):
        for cmd in ('for l in ${(s:,:)x#*:}; do sed -n ${l}p f; done', 'f=${x%%:*}; echo $f', 'echo ${x#*:}',
                    'echo ${path/a/b}', 'echo ${m:a}', 'echo ${#arr[@]}x${arr[1]%.java}'):
            self.assertTrue(self.blocked(cmd), cmd)
        for cmd in ('echo ${HOME}', 'echo ${x:-default}', 'echo "${T[@]}"', './buildw ${p}:spotlessApply', 'echo $x',
                    "python3 - <<'EOF'\nprint('${x#y}')\nEOF"):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_heredoc_bodies_are_not_commands(self):
        for cmd in ("git commit -qF - <<'EOF'\ndon't stop\ngit push\nEOF", "cat > f <<EOF\ngit stash\nEOF\necho ok",
                    "cat <<-X\n\tgit checkout\n\tX"):
            self.assertFalse(self.blocked(cmd), cmd)
        self.assertTrue(self.blocked("cat > f <<EOF\nx\nEOF\ngit stash"))

    def test_unparsable_command_is_blocked(self):
        self.assertTrue(self.blocked("git checkout 'unterminated"))

    def test_blocks_unbraced_zsh_modifiers(self):
        for cmd in ("./buildw $m:u", "echo $f:a", "echo $p:h/x"):
            self.assertTrue(self.blocked(cmd), cmd)
        for cmd in ("./buildw ${m}:test", "curl $HOST:8080", "echo $x: y"):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_deny_read_hits_resolve_every_token(self):
        root = "/r"
        rules = ["Read(//r/.claude/hooks/**)", "Read(//r/AGENTS.md)", "Edit(//r/x/**)"]
        cwd = "/r/svc/platform-services/alpha"
        for cmd in ("cat ../../../.claude/hooks/x", "cd /r && tail .claude/hooks/x", "less /r/AGENTS.md",
                    "sh -c 'cat /r/.claude/hooks/a'", "echo `cat /r/AGENTS.md`", "git diff HEAD -- /r/.claude/hooks",
                    "awk 1 --file=/r/.claude/hooks/x"):
            self.assertTrue(g.deny_read_hits(cmd, cwd, rules, repo_top=root), cmd)
        self.assertTrue(g.deny_read_hits("git show HEAD:.claude/hooks/x", cwd, rules, repo_top=root))
        for cmd in ("cat .agents/workflow/README.md", "ls /r/.claude", "cat /r/x/y", "git show HEAD:AGENTS.md:x",
                    "git status"):
            self.assertEqual(g.deny_read_hits(cmd, cwd, rules, repo_top=root), [], cmd)

    def test_deny_read_double_star_matches_zero_levels(self):
        """· — `/**/`는 사이 단계 0개도 맞는다(최상위 .env)."""
        root, cwd = "/r", "/r/svc/platform-services/alpha"
        rules = ["Read(//r/**/.env)"]
        for cmd in ("cat /r/.env", "head -1 ../../../.env", "grep x < /r/.env", "cat </r/.env", "cat /r/a/b/.env"):
            self.assertTrue(g.deny_read_hits(cmd, cwd, rules, repo_top=root), cmd)
        for cmd in ("cat /r/.envrc", "cat /r/x.env", "cat /r/a/env"):
            self.assertEqual(g.deny_read_hits(cmd, cwd, rules, repo_top=root), [], cmd)
        self.assertTrue(g.deny_read_hits("cat /r/.env", cwd, ["Read(//r/**/**/.env)"], repo_top=root))
        self.assertTrue(g.deny_read_hits("cat /.env", cwd, ["Read(//**/.env)"], repo_top=root))
        self.assertTrue(g.deny_read_hits("cat /r/s/x", cwd, ["Read(//r/**/s/**)"], repo_top=root))
        self.assertEqual(g.deny_read_hits("cat /r/.env", cwd, [], repo_top=root), [])

    def test_deny_read_hits_for_list_and_build_task_are_not_paths(self):
        """for 목록 낱말과 git 밖 `:` 토큰(빌드 도구 작업 이름)은 경로가 아니다(cwd 아래, deny Read(<>/bootstrap/**))."""
        root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        svc = os.path.join(root, "svc")
        os.makedirs(os.path.join(svc, "bootstrap"))
        wrap = os.path.join(root, "run-wrap.sh")  # 인자를 그대로 돌리는 감싸기 스크립트(본문까지 읽힌다)
        with open(wrap, "w") as f:
            f.write('#!/bin/sh\nshift\nexec "$@"\n')
        rules = [f"Read(/{svc}/bootstrap/**)"]
        cmd = (f"zsh {wrap} t2./buildw $(for m in domain application outbound:env "
               "inbound:web bootstrap; do printf ':platform-services:alpha:%s:archLayerTest ' \"${m}\"; done) --console=plain")
        self.assertEqual(g.deny_read_hits(cmd, svc, rules, repo_top=root), [])
        beta = (f"zsh {wrap} t2./buildw $(for m in domain application inbound inbound:grpc "
                "inbound:grpc:api outbound bootstrap; do printf ':platform-services:beta:%s:check ' \"${m}\"; done) --console=plain")
        self.assertEqual(g.deny_read_hits(beta, svc, rules, repo_top=root), [])  # 사본 시험의 꼴
        for task in ("./buildw :platform-services:alpha:bootstrap:archLayerTest", "./buildw :platform-services:beta:bootstrap:check"):
            self.assertEqual(g.deny_read_hits(task, svc, rules, repo_top=root), [], task)
        for bad in ("cat bootstrap/x", "git show HEAD:svc/bootstrap/x", "for f in a; do cat bootstrap/x; done",
                    "for f in bootstrap/x; do cat $f; done", "for f in bootstrap/x; do cat \"$f\" | head; done",
                    "x=$(for f in bootstrap/*; do cat $f; done)"):
            self.assertTrue(g.deny_read_hits(bad, svc, rules, repo_top=root), bad)

    def test_comments_do_not_hide_later_lines(self):
        """주석 걷기 — shlex 기본 주석이 줄바꿈(` ; `) 뒤까지 삼키지 않는다."""
        self.assertIn(["cat", "/x"], list(g.segments("#!/bin/sh\ncat /x")))
        self.assertIn(["cat", "/x"], list(g.segments("cat a # c\ncat /x")))
        self.assertEqual(list(g.segments('echo "a #b" ${#x} a#b')), [["echo", "a #b", "${#x}", "a#b"]])
        self.assertTrue(g.deny_read_hits("# n\ncat /r/.env", "/", ["Read(//r/**/.env)"], repo_top="/"))
        self.assertTrue(self.blocked("# n\ngit stash"))

    def _script_dir(self):
        import tempfile
        t = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(t, "secret"))
        os.makedirs(os.path.join(t, "d"))
        files = {"s.sh": f"#!/bin/sh\n# 주석\ncat {t}/secret/x\n", "s.py": f"print(open('{t}/secret/x').read())\n",
                 "a.sh": "bash s.sh\n", "ok.sh": "#!/bin/sh\n# c\ncat ok.txt\n", "ok.py": "print(1)\n",
                 "bad.sh": 'echo "x\n', "ok.txt": "x\n"}
        for name, body in files.items():
            with open(os.path.join(t, name), "w") as f:
                f.write(body)
        os.chmod(os.path.join(t, "s.sh"), 0o755)
        with open("/bin/ls", "rb") as src, open(os.path.join(t, "bin"), "wb") as dst:
            dst.write(src.read())
        os.chmod(os.path.join(t, "bin"), 0o755)
        return t, [f"Read(/{t}/secret/**)"]

    def test_script_bodies_are_checked(self):
        """· — 진입점마다 deny 경로를 읽는 스크립트."""
        t, rules = self._script_dir()
        for cmd in ("bash s.sh", "sh s.sh", "zsh -x s.sh", "source s.sh", ". s.sh", "./s.sh", f"{t}/s.sh", "python3 s.py",
                    "python3 -W ignore s.py", "find . -name s.sh -exec bash s.sh \\;", "xargs bash s.sh", "bash a.sh",
                    "bash < s.sh", f"bash <<EOF\ncat {t}/secret/x\nEOF", "env A=1 bash s.sh", "true && bash s.sh"):
            self.assertTrue(g.deny_read_hits(cmd, t, rules, repo_top=t), cmd)

    def test_unreadable_scripts_are_blocked(self):
        """본문을 볼 수 없으면 막고 까닭을 남긴다."""
        t, rules = self._script_dir()
        for cmd in ('bash "$X"', "bash none.sh", "bash d", "bash bad.sh", "cat s.sh | bash", 'bash "$D"/x.sh',
                    "find . -exec bash {} \\;", "python3 none.py", "source `echo s.sh`",
                    "cat s.sh | bash; cat <<E\nhi\nE"):
            hits = g.deny_read_hits(cmd, t, rules, repo_top=t)
            self.assertTrue(hits, cmd)
            self.assertTrue(any("본문" in h or "동적" in h for h in hits), (cmd, hits))

    def test_allowed_scripts_pass(self):
        """허용돼야 할 실행."""
        t, rules = self._script_dir()
        for cmd in ("bash ok.sh", "python3 -m unittest discover", "python3 -W ignore ok.py", "python3 -c 'print(1)'",
                    "find . -name x -exec echo {} \\; -print", "./bin", "bash -c 'echo hi'", '"$JAVACMD" -version',
                    "./none-cmd", "cat ok.sh", "bash -o pipefail ok.sh", "bash --rcfile ok.txt ok.sh",
                    "perl -I lib ok.py"):
            self.assertEqual(g.deny_read_hits(cmd, t, rules, repo_top=t), [], cmd)


class AlphaLeadGuardTest(GuardCases, unittest.TestCase):
    LEAD = "/x/proj-alpha"


class BetaLeadGuardTest(GuardCases, unittest.TestCase):
    LEAD = "/x/proj-beta"


class StdinBodyGapTest(unittest.TestCase):
    """빈틈과 표준 입력 본문."""

    def setUp(self):
        import tempfile
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.root = os.path.join(self.t, "root")
        os.makedirs(os.path.join(self.root, "sub"))
        for f in (".env", "x", "sub/.env"):
            open(os.path.join(self.root, f), "w").close()
        self.rules = [f"Read({self.root}/.env)", f"Read({self.root}/**/.env)"]

    def hits(self, cmd, rules=None, cwd=None):
        return g.deny_read_hits(cmd, cwd or self.t, self.rules if rules is None else rules, repo_top=self.t)

    def test_stdin_scripts_with_visible_bodies(self):
        r = self.root
        for cmd in ("python3 - <<'E'\nprint({1: 2})\nE", "python3 <<E\nprint(1)\nE", "bash <<< 'echo hi'",
                    "python3 - <<'E'\nimport re; d={'a': {'b','c'}}\nE", "python3 - << 'E'\nprint(1)\nE",
                    "python3 -<<'E'\nprint(1)\nE"):
            self.assertEqual(self.hits(cmd), [], cmd)
        for cmd in (f"python3 - <<'E'\nopen('{r}/.env')\nE", f"bash <<< 'cat {r}/.env'", "bash <<< \"$x\"",
                    "python3 - <<E\nprint(\"$(cat f)\")\nE", "cat f | python3 -", f"bash -s <<< 'cat {r}/.env'"):
            self.assertTrue(self.hits(cmd), cmd)
        self.assertIn("echo x", g.drop_heredoc_bodies("bash <<< 'w'\necho x"))

    def test_deny_pattern_forms(self):
        r = self.root
        old = g.CASE_FOLD
        try:
            g.CASE_FOLD = True
            self.assertTrue(self.hits(f"cat {r}/.ENV"))
            self.assertTrue(self.hits(f"cat {r}/SUB/.Env"))
            g.CASE_FOLD = False
            self.assertEqual(self.hits(f"cat {r}/.ENV"), [])
        finally:
            g.CASE_FOLD = old
        pats = [p for p, _ in g.deny_patterns(["Read(.env)", "Read(**/.env)"], bases=("/a",))]
        self.assertIn("/a/.env", pats)
        self.assertIn("/a/**/.env", pats)
        for cmd in ("cat .env", "cat sub/.env"):
            self.assertTrue(self.hits(cmd, rules=["Read(.env)", "Read(**/.env)"], cwd=r), cmd)
        self.assertEqual(self.hits("cat x", rules=["Read(.env)"], cwd=r), [])
        link = os.path.join(self.t, "link")
        os.symlink(r, link)
        self.assertTrue(self.hits(f"cat {r}/sub/.env", rules=[f"Read({link}/**/.env)"]))
        self.assertTrue(self.hits(f"cat {link}/x", rules=[f"Read({r}/x)"]))
        self.assertTrue(self.hits(f"cat {r}/.env", rules=[f"Read({r}/sub/../.env)"]))
        self.assertEqual(g.deny_patterns(["Read(//**)"]), [("/", True)])
        self.assertTrue(self.hits("cat /etc/hosts", rules=["Read(//**)"]))

    def test_braces_and_pushd(self):
        r = self.root
        for cmd in (f"cat {r}/{{.env,x}}", f"cat {r}/{{x,{{.env,y}}}}", f"cat {r}/{{x,sub}}/.env",
                    f"cat {r}/x{{1..300}}{{a,b}}", f"pushd {r}; cat .env", f"pushd {r} && cat sub/.env"):
            self.assertTrue(self.hits(cmd), cmd)
        for cmd in ("mkdir -p x/{a,b}", "find . -exec echo {} \\;", "echo ${HOME}", "pushd; cat .env",
                    f"pushd -n {r}; cat .env", "echo {a,b", f"cat {r}/{{x}}"):
            self.assertEqual(self.hits(cmd), [], cmd)
        self.assertEqual(g._brace_expand("a{b,c}d"), ["abd", "acd"])
        self.assertEqual(g._brace_expand("f{1..3}"), ["f1", "f2", "f3"])
        self.assertIsNone(g._brace_expand("{1..20}{1..20}"))
        self.assertTrue(g.reason("pushd /x/proj-alpha && git commit -m x", LEAD))

    def test_recursive_reads_over_denied_paths(self):
        r = self.root
        for cmd in (f"grep -r SECRET {r}", f"grep -Rn x {r}", f"grep --recursive x {r}", f"rg x {r}", f"tar cf - {r}",
                    f"cp -a {r} {self.t}/y", f"cp -r {r} {self.t}/y", f"rsync -a {r}/ {self.t}/y", f"zip -r z.zip {r}",
                    f"grep -r x {self.t}", f"cd {r} && grep -r x ."):
            self.assertTrue(self.hits(cmd), cmd)
        self.assertTrue(self.hits(f"grep -r x {r}/sub", rules=[f"Read({r}/**/.env)"]))
        other = os.path.join(self.t, "other")
        os.makedirs(other)
        for cmd in (f"grep -rn x {other}", f"grep x {r}/x", f"cp {r}/x {other}/y", f"tar cf - {other}",
                    f"grep -r x {r}/sub"):
            self.assertEqual(self.hits(cmd, rules=[f"Read({r}/.env)"]), [], cmd)

    def test_module_reads_pass_but_recursive_reads_over_repo_block(self):
        """옛 모듈 시험 test_common_flows_still_pass의 판정 몫 — 합성 저장소의 모듈 자리에서(모듈 흐름 스크립트는 모듈 시험)."""
        top = os.path.join(self.t, "top")
        module = os.path.join(top, "svc", "platform-services", "m")
        for d in (".git", ".agents", ".claude", "svc/.agents", "beta", "svc/platform-services/m/domain",
                  "svc/platform-services/m/.agents/workflow"):
            os.makedirs(os.path.join(top, d))
        rules = [f"Read(/{top}/{x})" for x in (".agents/**", ".claude/**", ".env", "svc/.agents/**", "beta/**")]
        rules += [f"Read(/{top}/**/.env)"]
        for cmd in ("git status", "git log --oneline -3", "grep -rn deny_read_hits .agents/workflow", "rg -n x domain",
                    "python3 - <<'E'\nimport pathlib; p=pathlib.Path('x'); p.write_text(p.read_text().replace('a','b'))\nE",
                    "mkdir -p /tmp/gx35/{a,b}", "cp -r domain /tmp/gx35/d"):
            self.assertEqual(g.deny_read_hits(cmd, module, rules), [], cmd)
        for cmd in (f"grep -r x {top}/svc", f"cd {top} && rg x", f"cd {top}/svc; grep -rn x"):
            self.assertTrue(g.deny_read_hits(cmd, module, rules), cmd)

    def test_review_fixes(self):
        r = self.root
        big = os.path.join(r, "big")
        os.makedirs(big)
        for n in range(12):
            open(os.path.join(big, f"f{n}"), "w").close()
        old = (g.WALK_LIMIT, g.WALK_LIMIT_NAME)
        try:
            g.WALK_LIMIT = g.WALK_LIMIT_NAME = 5  # `**/.env`는 이름 꼬리라 WALK_LIMIT_NAME이 상한
            self.assertTrue(self.hits(f"grep -r x {big}", rules=[f"Read({r}/**/.env)"]))
            g.WALK_LIMIT = g.WALK_LIMIT_NAME = 1000
            self.assertEqual(self.hits(f"grep -r x {big}", rules=[f"Read({r}/**/.env)"]), [])
        finally:
            g.WALK_LIMIT, g.WALK_LIMIT_NAME = old
        for cmd in (f"cd {r} && rg -g '*.py' foo", f"cd {r} && grep -r --exclude-dir build foo",
                    f"cd {r} && grep -r -e a -e b", "python3 <<E\nopen(\"$HOME/.env\")\nE"):
            self.assertTrue(self.hits(cmd), cmd)
        self.assertTrue(self.hits("cat .env", rules=["Read(**/.env)"], cwd=r))

    def test_info_options_are_not_stdin_scripts(self):
        for cmd in ("python3 --version", "/usr/bin/python3 -V", "bash --version", "node --version", "python3 -h", "perl --help"):
            self.assertEqual(self.hits(cmd), [], cmd)
        self.assertTrue(self.hits("cat f | python3 -"))


class FlowScriptGapTest(unittest.TestCase):
    """흐름 스크립트·셸 변수·남은 빈틈·쓰기·과잉 막힘."""

    def setUp(self):
        import tempfile
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.root = os.path.join(self.t, "root")
        os.makedirs(os.path.join(self.root, "sub"))
        for f in (".env", "x", "x.sh", "sub/.env"):
            open(os.path.join(self.root, f), "w").close()
        self.rules = [f"Read({self.root}/.env)"]

    def hits(self, cmd, rules=None, cwd=None):
        return g.deny_read_hits(cmd, cwd or self.t, self.rules if rules is None else rules, repo_top=self.t)

    def test_shell_vars_and_base(self):
        r = self.root
        for cmd in (f"D={r}; cd $D; cat .env", f"D={r}; cd ${{D}}/sub && cat ../.env", f"cd {r}; cd /tmp; cd -; cat .env",
                    f"(cd {r}; cat .env)", f"echo $(D={r}; cat $D/.env)", "cd $UNKNOWN && bash x.sh",
                    "cd $UNKNOWN && grep -r x", "cd $UNKNOWN && rg x", f"D={r} && cat $D/.env",
):
            self.assertTrue(self.hits(cmd), cmd)
        for cmd in (f"( cd {r} ); cat .env", "cd $UNKNOWN; cat .env", 'cd "$(dirname x)" && ls', f"D={r} cat .env",
                    f"cd {r}; cd -; cat .env", "cd -; ls", f"cd $UNKNOWN; cat {self.t}/x"):
            self.assertEqual(self.hits(cmd), [], cmd)
        self.assertTrue(g.reason("D=/x/proj-alpha; cd $D && git commit -m x", LEAD))
        self.assertIsNone(g.reason("D=/x/other; cd $D && git commit -m x", LEAD))

    def test_read_gaps(self):
        r = self.root
        sc = os.path.join(self.t, "s.txt")
        with open(sc, "w") as f:
            f.write(f'x = read("{r}/.env")\n')
        for cmd in (f"cat $'{r}/.env'", f"find {r} -name .env -exec cat {{}} \\;", f"find -L {r} -name .env -exec cat {{}} +",
                    f"find {r} -name .env | xargs cat", f"git -C {r} grep x", f"cd {r} && git grep x",
                    f"echo a\\ #b; cat {r}/.env", f"echo $(true)#x; cat {r}/.env",
                    f"php {sc}", f"deno run {sc}", f"bun run {sc}", f"uv run python {sc}",
                    f"uv run --with x python {sc}", f"awk -f {sc} x", f"lua {sc}", "cd $UNKNOWN; find . -name x -exec cat {} \\;",
                    "cd $UNKNOWN && git grep x"):
            self.assertTrue(self.hits(cmd), cmd)
        other = os.path.join(self.t, "other")
        os.makedirs(other)
        for cmd in ("find . -name '*.py'", f"find {other} -name x -exec cat {{}} \\;", f"echo hi # cat {r}/.env",
                    f"git -C {other} grep x", "awk '{print $1}' x", f"find {r} -name .env"):
            self.assertEqual(self.hits(cmd), [], cmd)

    def test_bash_writes(self):
        r, t = self.root, self.t
        rules = [f"Edit({r}/**)"]
        for cmd in (f"echo x > {r}/a", f"echo x >{r}/a", f"echo x >>{r}/a", f"ls 2> {r}/e", f"ls 2>{r}/e", f"ls &> {r}/e",
                    f"tee {r}/a", f"tee -a /tmp/gx75 {r}/a", f"cp x {r}/", f"cp -t {r} x", f"mv {r}/x /tmp/gx75y",
                    f"rm -rf {t}", f"rm {r}/x", f"sed -i '' s/a/b/ {r}/x", f"sed -i.bak s/a/b/ {r}/x", f"perl -pi -e s/a/b/ {r}/x",
                    f"install x {r}/y", f"bash -c 'echo > {r}/a'", f"D={r}; touch $D/n", f"echo $(echo x > {r}/a)",
                    f"mkdir {r}/n", f"chmod -R 700 {t}", f"dd if=x of={r}/y", f"cd {r} && echo x > a", f"(cd {r}; touch a)",
                    f"tar -xf a.tar -C {r}", f"cd {r}; tar xf a.tar", f"unzip a.zip -d {r}", f"rsync -a x/ {r}/",
                    f"ln -s x {r}/l", f"sort -o {r}/s x", f"curl -o {r}/c u", f"find {t} -name x -exec rm {{}} \\;"):
            self.assertTrue(g.deny_write_hits(cmd, t, rules), cmd)
        for cmd in ("echo x 2>&1", "echo x >&2", "ls 2>/dev/null", f"echo x > {t}/out", f"mkdir -p {t}/build/x",
                    f"cat {r}/x", f"cp {r}/x {t}/y", f"sed s/a/b/ {r}/x", f"sed -n 1p {r}/x", "echo x | tee /tmp/gx75",
                    f"rm -rf {t}/other", f"(cd {r}); touch a", "cat <<'E' > /tmp/gx75\nx > " + r + "/a\nE",
                    f"grep x {r}/x > /tmp/gx75", f"git -C {t} commit -m x"):
            self.assertEqual(g.deny_write_hits(cmd, t, rules), [], cmd)
        self.assertTrue(g.deny_write_hits("cd $UNKNOWN && echo x > a", t, rules))  # : 모르는 자리 상대 쓰기는 막음
        self.assertEqual(g.deny_write_hits(f"echo x > {r}/a", t, [f"Read({r}/**)"]), [])
        self.assertTrue(g.deny_write_hits(f"echo x > {r}/a", t, [f"Write({r}/**)"]))
        h = os.path.join(t, "h")
        ws = f"{h}/.agents/home/claude/work-sessions"
        self.assertTrue(g.deny_write_hits(f"echo {{}} > {ws}/W-1/settings.json", t, [f"Edit(/{ws}/**)"]))

    def test_overblock_relief(self):
        r, t = self.root, self.t
        os.makedirs(os.path.join(t, "beta"))
        os.makedirs(os.path.join(t, ".agents"))
        prose = [f"Read({t}/beta/**)", f"Read({t}/.agents/**)"]
        for cmd in ("python3 -c 'print(\"see beta/** and .agents for x\")'",
                    "python3 - <<'E'\ns = 'rules live in beta/ and .agents/'\nprint(s)\nE"):
            self.assertEqual(self.hits(cmd, rules=prose), [], cmd)
        for cmd in ("python3 -c 'open(\"beta/x\")'", f"python3 -c 'open(\"{t}/.agents/x\")'"):
            self.assertTrue(self.hits(cmd, rules=prose), cmd)
        self.assertEqual(self.hits("bash <<< 'echo $HOME'"), [])
        for cmd in ('bash <<< "$x"', "bash <<< 'a'\"$x\"", f"bash <<< 'cat {r}/.env'"):
            self.assertTrue(self.hits(cmd), cmd)
        other = os.path.join(t, "other")
        os.makedirs(other)
        for cmd in (f"cp -r {other} {r}", f"rsync -a {other}/ {r}/", f"cd {other} && tar -xf a.tar -C {r}"):
            self.assertEqual(self.hits(cmd), [], cmd)
        self.assertTrue(self.hits(f"cp -r {r} {other}"))
        big = os.path.join(t, "big")
        os.makedirs(big)
        for n in range(12):
            open(os.path.join(big, f"f{n}"), "w").close()
        star = [f"Read({t}/**/.env)"]
        old = (g.WALK_LIMIT, g.WALK_LIMIT_NAME)
        try:
            g.WALK_LIMIT, g.WALK_LIMIT_NAME = 5, 1000
            self.assertEqual(self.hits(f"grep -r x {big}", rules=star), [])
            g.WALK_LIMIT_NAME = 5
            self.assertTrue(self.hits(f"grep -r x {big}", rules=star))
        finally:
            g.WALK_LIMIT, g.WALK_LIMIT_NAME = old
        self.assertIn("셸 변수에 담은 경로", " ".join(self.hits('bash "$F"')))

    def test_change_review_fixes(self):
        """6단계 (슈퍼파워 I1~I3·M1~M4)."""
        r, t = self.root, self.t
        w = [f"Edit({r}/**)"]
        for cmd in (f"echo hi>{r}/a", f"ls 2>{r}/a", f"echo x >| {r}/a", f"echo x 2>&1 >{r}/a"):
            self.assertTrue(g.deny_write_hits(cmd, t, w), cmd)
        self.assertTrue(self.hits(f"cat<{r}/.env"))
        for cmd in (f"cd -P {r}; cat .env", f"cd -- {r}; cat .env", f"cd -L {r} && cat .env",
                    f"export D={r}; cat $D/.env", f"declare -x D={r}; cat $D/.env", f"local D={r}; cat $D/.env"):
            self.assertTrue(self.hits(cmd), cmd)
        self.assertTrue(g.reason("cd $U; GIT_DIR=.git git commit -m x", LEAD))
        self.assertTrue(g.reason("cd -P /x/proj-alpha; git commit -m x", LEAD))
        self.assertIsNone(g.reason("echo \\$'x'", LEAD))
        sc = os.path.join(t, "ok.py")
        open(sc, "w").close()
        self.assertEqual(self.hits(f"python3 -I {sc}"), [])
        self.assertEqual(self.hits(f"python3 -X dev {sc}"), [])

    def test_change_review_fixes_ours(self):
        """6단계 (우리 C1·I1~I4·M1·M2)."""
        r, t = self.root, self.t
        for cmd in ("cd $U; git -C a -C b commit -m x", "cd $U; GIT_DIR=.git git -C sub commit -m x",
                    "cd $U; GIT_WORK_TREE=w git --git-dir=d commit -m x"):
            self.assertTrue(g.reason(cmd, LEAD), cmd)
        self.assertTrue(g.reason("cd $U; git -C a -C b commit", LEAD))  # 훅 진입으로는 test_guard
        for cmd in (f"cp -r -t /tmp/gx75o {r}", f"cp -rt /tmp/gx75o {r}"):
            self.assertTrue(self.hits(cmd), cmd)
        w = [f"Edit({r}/**)"]
        for cmd in (f"rsync -a -t x {r}/a", f"echo x >&{r}/a", f"install -d {r}/x"):
            self.assertTrue(g.deny_write_hits(cmd, t, w), cmd)
        self.assertEqual(g.deny_write_hits(f"tar --exclude=a -cf /tmp/gx75.tar -C {r} .", t, w), [])
        self.assertTrue(g.deny_write_hits(f"tar -xf a.tar -C {r}", t, w))
        self.assertTrue(g.deny_write_hits(f"tar xf a.tar -C {r}", t, w))

    def test_escaped_subs_are_not_local(self):
        r = self.root
        self.assertEqual(self.hits(f'echo "\\$(cat {r}/.env)"'), [])
        self.assertEqual(self.hits(f'echo "\\`cat {r}/.env`"'), [])
        self.assertTrue(self.hits(f'echo "$(cat {r}/.env)"'))
        self.assertTrue(self.hits(f'echo "\\\\$(cat {r}/.env)"'))


class WriteGapTest(unittest.TestCase):
    """쓰기 판정 빈틈·과잉 막힘."""

    def setUp(self):
        import tempfile
        self.t = os.path.realpath(tempfile.mkdtemp())
        t = self.t
        for d in ("a/.agents/rules", "b/.agents/rules", "x/tmp", "y", "deny", "src", "out"):
            os.makedirs(os.path.join(t, d))
        for f in ("a/.agents/rules/r.md", "deny/s.json", "src/f", ".env"):
            open(os.path.join(t, f), "w").close()
        self.rules = [f"Edit(/{t}/*/.agents/rules/**)", f"Edit(/{t}/deny/**)", f"Edit(/{t}/y/b)", f"Edit(/{t}/out/src/**)"]

    def w(self, cmd, cwd=None):
        return g.deny_write_hits(cmd, cwd or os.path.join(self.t, "x"), self.rules, repo_top=self.t)

    def test_overblock_relief(self):
        t = self.t
        for cmd in ("tar xzf f.tgz", "unzip f.zip", f"rm -r {t}/x/tmp", f"echo 'x>{t}/deny/a'", f'echo "a<{t}/deny/a"'):
            self.assertEqual(self.w(cmd), [], cmd)
        for cmd in (f"rm -r {t}/a", f"tar xzf f.tgz -C {t}/a/.agents/rules", f"cd {t}/deny && unzip f.zip",
                    f"sh -c 'echo hi > {t}/deny/a'", f'eval "echo > {t}/deny/a"',
                    f"find . -exec sh -c 'echo > {t}/deny/a' \\;", f"bash -c \"echo 'q' > {t}/deny/a\""):
            self.assertTrue(self.w(cmd), cmd)
        self.assertEqual(g.deny_read_hits(f"cat 'a<{t}/.env'", t, [f"Read({t}/.env)"], repo_top=t), [])
        self.assertTrue(g.deny_read_hits(f"sh -c 'cat < {t}/.env'", t, [f"Read({t}/.env)"], repo_top=t))

    def test_write_expansion_xargs_redirect_unknown_base(self):
        t = self.t
        for cmd in (f"touch {t}/{{x,y}}/b", f"sed -i s/a/b/ {t}/*/.agents/rules/*.md", f"find {t}/deny | xargs rm",
                    f"find {t}/deny -print0 | xargs -0 touch", f"cp x {t}/deny/a 2> /dev/null",
                    f"ln -s x {t}/deny/a 2> /dev/null", f'cd "$(echo {t}/deny)" && echo > rel',
                    'cd "$(git rev-parse --show-toplevel)" && echo x > rel'):  # 마지막 줄: 비용(모르는 자리 상대 쓰기)
            self.assertTrue(self.w(cmd), cmd)
        for cmd in (f"find {t}/src | xargs -I{{}} cp {{}} {t}/x/", f"cp x {t}/x/o 2> /dev/null", f"touch {t}/{{x,src}}/b",
                    f"find {t}/deny -name q | xargs grep z", "ls 2> /dev/null"):
            self.assertEqual(self.w(cmd), [], cmd)

    def test_links_copies_git_writes(self):
        t = self.t
        with open(os.path.join(t, "x", "p.diff"), "w") as f:
            f.write("--- a/deny/s.json\n+++ b/deny/s.json\n@@ -0,0 +1 @@\n+x\n")
        with open(os.path.join(t, "x", "ok.diff"), "w") as f:
            f.write("--- a/x/q\n+++ b/x/q\n@@ -0,0 +1 @@\n+x\n")
        for cmd in (f"ln -s {t}/deny L; echo hi > L/z", f"ln -sf {t}/deny L && touch L/a/b", f"cp -r {t}/src {t}/out",
                    f"cp -R src {t}/out/src/n", f"git mv q {t}/deny/q", f"git -C {t}/deny rm s.json", f"git rm -r {t}/deny",
                    f"git checkout-index --prefix={t}/deny/ -a", f"git checkout-index -f -- {t}/deny/s.json",
                    f"git apply --directory={t}/deny p.diff", "git apply p.diff", "git apply", "git apply nope.diff"):
            self.assertTrue(self.w(cmd), cmd)
        for cmd in (f"ln -s {t}/deny L", f"ln -s {t}/src L; echo hi > L/z", f"cp -r {t}/src {t}/x/o", f"cp -r {t}/deny {t}/x/o",
                    "git apply --check p.diff", "git apply ok.diff", "git add x", "git commit -m m", f"git mv {t}/x/a {t}/x/b",
                    "git checkout-index -a"):
            self.assertEqual(self.w(cmd), [], cmd)

    def test_same_path_walks_once(self):
        from unittest import mock
        t = self.t
        rules = [f"Edit(/{t}/**/deep.txt)"]
        with mock.patch.object(g, "_walk_hits", return_value=False) as walk:
            g.deny_write_hits(f"rm -r {t}/x", t, rules)
        self.assertEqual(walk.call_count, 1)

    def test_change_review_write_gaps(self):
        """이름 바꾸기·이진·-pN 패치, --stat --apply, checkout-index -n, --work-tree, cp -R src/, ln --symbolic."""
        t, x = self.t, os.path.join(self.t, "x")
        patches = {"ren.diff": "diff --git a/x/q b/deny/q\nsimilarity index 100%\nrename from x/q\nrename to deny/q\n",
                   "bin.diff": "diff --git a/deny/b.bin b/deny/b.bin\nnew file mode 100644\nGIT binary patch\nliteral 1\nIcmZ?d00001\n",
                   "p2.diff": "--- x/a/deny/s.json\n+++ x/b/deny/s.json\n@@ -0,0 +1 @@\n+x\n",
                   "ok.diff": "--- a/x/q\n+++ b/x/q\n@@ -0,0 +1 @@\n+x\n",
                   "empty.diff": "nothing here\n"}
        for name, body in patches.items():
            with open(os.path.join(x, name), "w") as f:
                f.write(body)
        os.makedirs(os.path.join(t, "src", "deny"))
        for cmd in ("git apply ren.diff", "git apply bin.diff", "git apply -p2 p2.diff", "git apply empty.diff",
                    f"git apply --stat --apply {x}/p2.diff -p2", f"git checkout-index -n -- {t}/deny/s.json",
                    f"git --work-tree={t}/deny checkout-index -f -- s", f"GIT_WORK_TREE={t}/deny git checkout-index -f -- s",
                    f"cp -R {t}/src/ {t}", f"ln --symbolic {t}/deny L && echo > L/z"):
            self.assertTrue(self.w(cmd), cmd)
        for cmd in ("git apply ok.diff", "git apply --stat ok.diff", "git apply -p1 ok.diff", f"git rm -n {t}/deny/s.json",
                    f"cd {t} && tar xzf f.tgz"):  # 마지막: 비용 — deny 부모 자리 풀기는 통과(아카이브 안은 못 봄)
            self.assertEqual(self.w(cmd), [], cmd)

    def test_deep_glob_target_is_bounded(self):
        import time
        start = time.time()
        with mock_limit(g, 2):
            found = self.w(f"touch {self.t}/*/*")
        self.assertLess(time.time() - start, 5)
        self.assertTrue(any("너무 크다" in h for h in found), found)


class InterpreterWriteTest(unittest.TestCase):
    """인터프리터 본문(인라인·heredoc·here-string)의 쓰기도 Edit deny로."""

    def setUp(self):
        import tempfile
        self.t = os.path.realpath(tempfile.mkdtemp())
        t = self.t
        for d in ("svc/tools/guard-hooks", "svc/mod/x", "svc/mod/.agents/workflow", "out"):
            os.makedirs(os.path.join(t, d))
        open(os.path.join(t, "svc/tools/guard-hooks/guard_bash.py"), "w").close()
        self.cwd = os.path.join(t, "svc/mod/x")
        self.rules = [f"Edit(/{t}/svc/tools/**)", f"Edit(/{t}/svc/mod/.agents/workflow/**)"]

    def w(self, cmd, cwd=None):
        return g.deny_write_hits(cmd, cwd or self.cwd, self.rules, repo_top=self.t)

    def test_inline_writes_to_deny_are_blocked(self):
        t = self.t
        for cmd in ("python3 -c \"open('../../tools/guard-hooks/x','w')\"",  # 재현
                    f"python -c \"open('{t}/svc/tools/guard-hooks/x', 'a').write('y')\"",
                    "python3 -c \"import pathlib; pathlib.Path('../../tools/x').write_text('y')\"",
                    "python3 -c \"import pathlib; pathlib.Path('../.agents/workflow/s.json').write_bytes(b'')\"",
                    "python3 -c \"import shutil; shutil.copy('a', '../../tools/guard-hooks/guard_bash.py')\"",
                    "python3 -c \"import shutil; shutil.move('a', '../../tools/x')\"",
                    "python3 -c \"import os; os.rename('a', '../../tools/x')\"",
                    "python3 -c \"import os; os.replace('a', '../../tools/x')\"",
                    "python3 -c \"import os; os.remove('../../tools/guard-hooks/guard_bash.py')\"",
                    "python3 -c \"import os; os.unlink('../../tools/guard-hooks/guard_bash.py')\"",
                    "python3 -c \"p='../../tools/x'; f=open(p, mode='w')\"",  # 변수 한 단계
                    "python3 -c \"import os; open(os.path.join('../..', 'tools', 'guard-hooks', 'x'), 'w')\"",
                    "python3 -c \"open('../../tools/' + 'guard-hooks/x', 'w')\"",
                    "python3 -c \"import shutil; shutil.rmtree('../..')\"",  # deny를 아래에 둔 부모
                    "python3 -c \"import subprocess; subprocess.run(['cp', 'a', '../../tools/x'])\"",
                    "python3 -Ic \"open('../../tools/x','w')\"", "python3 -c\"open('../../tools/x','w')\"",
                    "node -e \"require('fs').writeFileSync('../../tools/x', '')\"",
                    "node -e \"require('fs').copyFileSync('a', '../../tools/x')\"",
                    "node --eval \"require('fs').unlinkSync('../../tools/guard-hooks/guard_bash.py')\"",
                    "perl -e 'open(F, \">../../tools/x\"); print F 1'",
                    "perl -e 'open(my $f, \">>\", \"../../tools/x\")'", "perl -le 'unlink \"../../tools/x\"'",
                    "ruby -e 'File.write(\"../../tools/x\", \"y\")'", "ruby -e 'File.open(\"../../tools/x\", \"w\")'",
                    "python3 - <<'E'\nopen('../../tools/x', 'w').write('y')\nE",
                    "python3 <<'E'\nimport os\nos.remove('../../tools/guard-hooks/guard_bash.py')\nE",
                    "python3 <<< \"open('../../tools/x','w')\"",
                    "sh -c \"python3 -c \\\"open('../../tools/x','w')\\\"\"",
                    f"cd {t}/svc && python3 -c \"open('tools/x','w')\"",
                    "env PYTHONPATH=. python3 -c \"open('../../tools/x','w')\""):
            self.assertTrue(self.w(cmd), cmd)

    def test_shell_strings_argv_and_nested_strings(self):
        """전 스스로 찾은 빈틈: 코드 안 셸 명령 문자열(공백 든 문자열), 코드 뒤 셸 인자(sys.argv), 문자열 안 문자열(exec)."""
        for cmd in ("python3 -c 'import os; os.system(\"touch ../../tools/x\")'",
                    "python3 -c \"import subprocess; subprocess.run('cp a ../../tools/x', shell=True)\"",
                    "python3 -c \"import sys; open(sys.argv[1],'w')\" ../../tools/x",
                    "node -e \"require('fs').writeFileSync(process.argv[1], '')\" ../../tools/x",
                    "python3 - ../../tools/x <<'E'\nimport sys; open(sys.argv[1], 'w')\nE",
                    "python3 -c \"exec(\\\"open('../../tools/x','w')\\\")\"",
                    "python3 -c \"m='w'; open('../../tools/x', m)\"",
                    "python3 -c \"import os; os.chdir('../../tools'); open('guard-hooks/x','w')\"",
                    "python3 -c \"import os; os.chdir('../..'); open('tools/x','w')\"",
                    "python3 -c \"import os; os.chdir(os.environ['D']); open('x','w')\"",
                    "ruby -e 'Dir.chdir(ENV[\"D\"]); File.write(\"x\", \"y\")'",
                    "python3 - <<'E'\nimport pathlib\nfor p in pathlib.Path('../..').rglob('*.py'):\n    p.write_text('')\nE", "perl -e 'my $m=\">\"; open(F, $m, \"../../tools/x\")'"):
            self.assertTrue(self.w(cmd), cmd)
        for cmd in ("python3 -c \"import sys; print(open(sys.argv[1]).read())\" ../../tools/x",
                    "python3 -c \"import os; os.system('ls ../../tools')\" > /tmp/gx36-out",
                    "python3 -c \"d={'a': 1}; print(open('../../tools/x').read(), d['a'])\"",
                    "python3 -c \"import os; os.chdir('/tmp'); open('x','w')\"",
                    "python3 -c \"print(\\\"don't stop\\\"); import os; os.system('echo hi')\"",
                    "python3 - <<'E'\nimport pathlib\nfor p in pathlib.Path('.').rglob('*.py'):\n    p.write_text('')\nE"):
            self.assertEqual(self.w(cmd), [], cmd)

    def test_reads_outside_writes_and_flow_forms_pass(self):
        t = self.t
        for cmd in ("python3 -c \"print(open('../../tools/guard-hooks/guard_bash.py').read())\"",
                    "python3 -c \"import json; d=json.load(open('../.agents/workflow/s.json')); print(d)\"",
                    f"python3 -c \"open('{t}/out/x','w').write('y')\"", "python3 -c \"open('../../../out/x','w')\"",
                    "python3 -c 'print(1)'", "python3 -c \"print('see ../../tools for x')\"",
                    "python3 - <<'E'\nimport pathlib; p=pathlib.Path('x'); p.write_text(p.read_text().replace('a','b'))\nE",
                    "python3 - <<'E'\nprint({1: 2})\nE", "python3 -c \"print('../../tools/x'.replace('a', 'b'))\"",
                    "node -e \"console.log(require('fs').readFileSync('../../tools/x', 'utf8'))\"",
                    "perl -e 'open(F, \"<../../tools/x\"); print <F>'",
                    "ruby -e 'puts File.read(\"../../tools/x\")'",
                    f"perl -pi -e s/a/b/ {t}/out/x", "python3 -c \"import os; p=os.environ['P']; open(p,'w')\"",
                    "perl -e 'open(F, \">$ENV{D}/x\")'",  # 동적 경로 — 과 같이 통과
                    "python3 x.py", "python3 -m unittest discover"):
            self.assertEqual(self.w(cmd), [], cmd)
        self.assertTrue(self.w(f"perl -pi -e s/a/b/ {t}/svc/tools/x"))  # 셸 쓰기 대상 판정 그대로

    def test_unknown_base_and_unseen_bodies(self):
        for cmd in ("cd $UNKNOWN && python3 -c \"open('x/y','w')\"", "cat f | python3 -",
                    "python3 <<< \"$CODE\"", "python3 <<E\nopen('$P','w')\nE"):
            self.assertTrue(self.w(cmd), cmd)
        for cmd in ("cd $UNKNOWN && python3 -c \"print(open('/etc/hosts').read())\"",
                    "cd $UNKNOWN && python3 -c 'print(1)'"):
            self.assertEqual(self.w(cmd), [], cmd)

    def test_inline_forms_seen_by_read_judgment_too(self):
        r = os.path.join(self.t, "out")
        open(os.path.join(r, ".env"), "w").close()
        rules = [f"Read({r}/.env)"]
        for cmd in (f"python3 -Ic \"open('{r}/.env')\"", f"perl -ne 'print' {r}/.env", f"node -p \"require('fs').readFileSync('{r}/.env')\"",
                    f"perl -e 'open(F, \"<{r}/.env\"); print <F>'"):
            self.assertTrue(g.deny_read_hits(cmd, self.t, rules), cmd)
        for cmd in ("python3 -Ic 'print(1)'", "perl -le 'print 1'", "node -p '1+1'", "ruby -ne 'puts $_' /tmp/x"):
            self.assertEqual(g.deny_read_hits(cmd, self.t, rules), [], cmd)


class OverBlockReliefTest(unittest.TestCase):
    """과잉 막힘 셋: 3.9 글롭 예외, 같은 명령 안 heredoc으로 만든 스크립트, 본문의 경로 아닌 글자."""

    def setUp(self):
        import tempfile
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.root = os.path.join(self.t, "root")
        os.makedirs(os.path.join(self.root, "sub"))
        for f in (".env", "x", "sub/.env"):
            open(os.path.join(self.root, f), "w").close()
        self.env = os.path.join(self.root, ".env")
        self.rules = [f"Read({self.root}/.env)", f"Read({self.root}/**/.env)", f"Edit({self.root}/sub/**)"]

    def r(self, cmd, cwd=None):
        return g.deny_read_hits(cmd, cwd or self.t, self.rules, repo_top=self.t)

    def put(self, name, text, mode=0o644):
        path = os.path.join(self.t, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def test_glob_that_cannot_become_a_regex_is_a_literal(self):
        """① 3.9 fnmatch는 `[^-[`를 `re.error: bad character range`로 — 판정 예외(막음)가 아니라 글자로 본다(펼치지 않음)."""
        self.put("w", "#!/bin/sh\nquote() { printf %s\\\\n \"$1\" | sed ' s~[^-[:alnum:]+,./:=@_]~\\\\&~g; '; }\n", 0o755)
        self.assertEqual(self.r("./w -q help"), [])  # 실물 buildw 본문의 sed 식
        self.assertEqual(self.r("ls [^-[]x"), [])
        self.assertEqual(g.deny_write_hits("touch [^-[]x", self.t, self.rules, repo_top=self.t), [])
        self.assertTrue(g.deny_write_hits("touch sub/[^-[]x", self.root, self.rules, repo_top=self.t))  # 글자 자리가 deny 안
        self.assertTrue(self.r(f"cat {self.env} [^-[]x"))  # 같은 명령의 deny 글자는 그대로 막음

    def test_script_written_by_heredoc_in_same_command(self):
        """② 판정 때 아직 없는 스크립트를 같은 명령 앞 조각이 heredoc으로 만들면 그 본문을 스크립트 본문으로 본다."""
        for cmd in ("cat > f.py <<'E' && python3 f.py\nprint(1)\nE",
                    "cat <<'E' >f.py\nprint(1)\nE\npython3 f.py",
                    "cat >>f.py <<-'E'; python3 f.py\n\tprint(1)\n\tE",
                    "tee f.py <<'E' >/dev/null\nprint(1)\nE\npython3 f.py",
                    "cat > f.sh <<'E' && bash f.sh\necho hi\nE",
                    f"cat > f.py <<'E' && python3 f.py {self.t}/x\nprint(1)\nE",
                    "cat > f.py << 'E' && python3 f.py\nprint(1)\nE", "cat > f.py <<-  E; python3 f.py\n\tprint(1)\n\tE"):  # 띄어 쓴 끝말
            self.assertEqual(self.r(cmd), [], cmd)
        for cmd in (f"cat > f.py <<'E' && python3 f.py\nprint(open('{self.env}').read())\nE",
                    f"cat > f.sh <<'E' && bash f.sh\ncat {self.env}\nE",
                    "cat > f.py <<E && python3 f.py\nprint(open('$P').read())\nE",  # 바깥 셸이 펼치는 본문
                    "cat > g.py <<'E' && python3 f.py\nprint(1)\nE",  # 다른 파일 — 여전히 본문을 못 읽음
                    "echo 'print(1)' > f.py && python3 f.py"):  # heredoc 밖으로 만든 파일은 그대로(못 봄 → 막음)
            self.assertTrue(self.r(cmd), cmd)

    def test_non_path_strings_in_script_bodies(self):
        """③ 인터프리터 본문의 `/` 없는 문자열은 호출 인자 자리일 때만 경로 후보다(deny 규칙을 만드는 글자 `".env"`)."""
        body = ('import os\nTOP = "/r"\nrules = [f"Read(/{TOP}/{x})" for x in (".agents/**", ".env")]\n'
                'rules += [f"Read(/{TOP}/**/.env)"]\nNAME = ".env"\nif (".env" in NAME):\n    pass\n'
                'D = {".env": 1}\nprint(".env")\n')
        self.put("flow_test.py", body)
        for cmd in (f"python3 {self.t}/flow_test.py", f"python3 - <<'E'\n{body}E", "python3 -c \"x = '.env'\""):
            self.assertEqual(self.r(cmd, cwd=self.root), [], cmd)
        for code in ("print(open('.env').read())", "import subprocess\nsubprocess.run(['cat', '.env'])",
                     "import pathlib\npathlib.Path('.env').read_text()", "f = open(\n    '.env')",
                     "import os\nopen(os.path.join(os.getcwd(), '.env'))", "x = 'sub/.env'",
                     f"X = '{self.env}'", "print(open( \".env\" ).read())"):
            self.put("bad.py", code + "\n")
            self.assertTrue(self.r(f"python3 {self.t}/bad.py", cwd=self.root), code)
            self.assertTrue(self.r(f"python3 - <<'E'\n{code}\nE", cwd=self.root), code)


class NameFilterOptionTest(unittest.TestCase):
    """이름 거르기 옵션 값(`--include=*.md` 등)은 경로가 아니다."""

    def setUp(self):
        import tempfile
        self.top = os.path.realpath(tempfile.mkdtemp())  # 홈 deny 꼴: 저장소 꼭대기의 README.md·package.json
        os.makedirs(os.path.join(self.top, "svc/platform-services/beta"))
        for f in ("README.md", "package.json", "svc/platform-services/beta/a.md"):
            open(os.path.join(self.top, f), "w").close()
        self.rules = [f"Read({self.top}/README.md)", f"Read({self.top}/package.json)"]

    def r(self, cmd, cwd=None):
        return g.deny_read_hits(cmd, cwd or self.top, self.rules, repo_top=self.top)

    def test_name_filter_option_values_are_not_paths(self):
        for cmd in ("grep -rln '전달용\\|guard/pre_tool' svc/platform-services/beta --include='*.md' --include='*.py'"
                    " --include='*.sh' --include='*.json'",  # 실제 꼴
                    "grep -rn x svc --include=README.md --exclude=package.json --exclude-dir=node_modules",
                    "grep -rn x svc --exclude-dir=*.json", "grep -rn x svc --include-dir=README.md",
                    "egrep -r x svc --include=*.json", "rg -n x svc --glob=*.md --iglob=*.JSON",
                    "rsync -a --exclude=*.md --include=package.json svc /tmp/o",
                    "tar -cf /tmp/o.tar --exclude=README.md svc", "du -sh --exclude=*.json svc",
                    "diff -r --exclude=*.md svc /tmp/o"):
            self.assertEqual(self.r(cmd), [], cmd)

    def test_paths_stay_judged(self):
        """새로 덜 막는 것은 위 옵션 값뿐 — 경로 인자·경로를 받는 옵션·목록 밖 명령은 그대로 막는다."""
        for cmd in ("grep -rn x README.md --include=*.md", "grep -n x --file=README.md svc",
                    "grep -rn x --exclude-from=package.json svc", "rg -n x --ignore-file=package.json svc",
                    "rsync -a --exclude-from=package.json svc /tmp/o", "cc --include=README.md x.c",
                    "grep -rn x --include=*.md",  # 경로 없는 재귀 — cwd(꼭대기)를 통째로 읽는다
                    f"grep -rn x {self.top} --include=*.md"):
            self.assertTrue(self.r(cmd), cmd)


class DenyGlobShapeTest(unittest.TestCase):
    """deny 글롭은 Claude Code 권한 꼴: `*`·`?`·`[...]`는 한 단계, `**`만 여러 단계."""

    def setUp(self):
        import tempfile
        self.top = os.path.realpath(tempfile.mkdtemp())
        self.app = os.path.join(self.top, "svc/platform-services/beta/application")
        os.makedirs(os.path.join(self.app, "src/a"))
        for f in ("svc/build.conf.kts", "svc/settings.conf.kts", "svc/platform-services/beta/application/build.conf.kts",
                  ".env", "svc/platform-services/beta/application/src/a/.env"):
            open(os.path.join(self.top, f), "w").close()
        self.w = [f"Edit({self.top}/svc/*.conf.kts)", f"Write({self.top}/svc/*.conf.kts)"]

    def wr(self, cmd, rules=None, cwd=None):
        return g.deny_write_hits(cmd, cwd or self.top, rules or self.w, repo_top=self.top)

    def test_star_does_not_cross_slash(self):
        """실제 꼴: 모듈 빌드 파일 Bash 쓰기는 루트 빌드 deny에 안 걸린다(Edit 도구 판정과 같게)."""
        mod = "svc/platform-services/beta/application/build.conf.kts"
        for cmd in (f"echo x >> {self.top}/{mod}", f"cat > {mod} <<'E'\nx\nE", f"sed -i '' s/a/b/ {self.app}/build.conf.kts",
                    "echo x > build.conf.kts"):
            cwd = self.app if cmd.startswith("echo x > build") else None
            self.assertEqual(self.wr(cmd, cwd=cwd), [], cmd)
        for rule, path in ((f"Edit({self.top}/svc/?/x)", "svc/a/b/x"),
                           (f"Edit({self.top}/svc/a?b/x)", "svc/a/b/x"),
                           (f"Edit({self.top}/svc/[pq]*/x)", "svc/platform-services/beta/x"),
                           (f"Edit({self.top}/*/x)", "svc/platform-services/x")):
            self.assertEqual(self.wr(f"touch {self.top}/{path}", [rule]), [], rule)
        self.assertEqual(g.deny_read_hits(f"cat {self.app}/build.conf.kts", self.top, [f"Read({self.top}/svc/*.conf.kts)"],
                                          repo_top=self.top), [])

    def test_root_build_and_double_star_stay_blocked(self):
        """막아야 할 것은 그대로: 루트 빌드 파일, `**` deny의 깊은 자리(0개 단계 포함), 끝 `/**` 나무, 한 단계 글롭."""
        for cmd in (f"echo x >> {self.top}/svc/build.conf.kts", f"echo x > {self.top}/svc/settings.conf.kts",
                    "sed -i '' s/a/b/ svc/build.conf.kts"):
            self.assertTrue(self.wr(cmd), cmd)
        deep = [f"Edit({self.top}/**/.env)", f"Read({self.top}/**/.env)"]
        for path in (".env", "svc/platform-services/beta/application/src/a/.env"):
            self.assertTrue(self.wr(f"echo x > {self.top}/{path}", deep), path)
            self.assertTrue(g.deny_read_hits(f"cat {self.top}/{path}", self.top, deep, repo_top=self.top), path)
        self.assertTrue(self.wr(f"echo x > {self.app}/src/a/new", [f"Edit({self.top}/svc/**)"]))
        self.assertTrue(self.wr(f"echo x > {self.app}/src/a/new", [f"Edit({self.top}/svc/*/beta/**)"]))
        self.assertTrue(self.wr(f"touch {self.top}/svc/a/x", [f"Edit({self.top}/svc/?/x)"]))
        self.assertTrue(self.wr(f"touch {self.top}/svc/p1/x", [f"Edit({self.top}/svc/[pq]*/x)"]))
        self.assertTrue(self.wr(f"touch {self.top}/svc/a/b/x", [f"Edit({self.top}/svc/**/b/x)"]))

    def test_glob_match_unit(self):
        m = g._glob_match
        self.assertTrue(m("/t/svc/build.conf.kts", "/t/svc/*.conf.kts"))
        self.assertFalse(m("/t/svc/p/a/build.conf.kts", "/t/svc/*.conf.kts"))
        self.assertTrue(m("/t/a/b/c", "/t/**"))
        self.assertTrue(m("/t/a/b/.env", "/t/**/.env"))
        self.assertFalse(m("/t/a/b", "/t/a?b"))
        self.assertFalse(m("/t/a/b", "/t/a[!x]b"))  # 부정 괄호도 `/`는 아님
        self.assertFalse(m("/t/a/b", "/t/a[/]b"))
        self.assertTrue(m("/t/[x", "/t/[x"))  # 닫히지 않은 괄호는 글자
        self.assertFalse(m("/t/b", "/t/[z-a]"))  # 정규식으로 못 바뀌는 패턴 — 예외 없이 글자 그대로만
        self.assertTrue(m("/t/[z-a]", "/t/[z-a]"))


class GlobDotDotTest(unittest.TestCase):
    """glob 뒤 `..` 마디: Claude Code가 bypass에서도 확인 창을 띄우는 꼴을 공통 훅이 먼저 거절한다."""

    ORIGIN = "cat $P/domain/src/main/java/*/../ -h; find …; grep …"  # 어가 멈춘 명령 원문

    def words(self, cmd):
        return g.glob_dotdot_words(cmd)

    def test_origin_command_is_caught(self):
        self.assertEqual(self.words(self.ORIGIN), ["$P/domain/src/main/java/*/../"])

    def test_glob_then_dotdot_is_caught(self):
        for cmd in ("ls src/*/../x", "cat a?/..", "ls [ab]/../c", "x=$(ls */..)", "ls a/*/b/../c",
                    "grep -rn x src/*/..", "cat \"$D\"/*/../f", "ls *'/'..", "echo ok && ls p/*/../../q",
                    "find . -path x | xargs ls */../y", "ls --dir=*/../x"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.words(cmd), cmd)

    def test_not_glob_then_dotdot_passes(self):
        for cmd in ("grep -rn '*/../' .", 'grep -rn "src/*/../" .', "ls ../*", "ls ../../*.md", "ls ../a/*",
                    "git diff a...b", "git log main..HEAD", "echo {1..3}", "ls a*..b", "ls a*/..b", "ls a*/b..",
                    "ls \\*/../x", "ls x/\\?/../y", "[ -d ../x ]", "echo '*' ..", "ls * ..",
                    "cat <<'E'\nls */../x\nE", "cat <<E\nls */../x\nE\necho ok", "ls x # */../y",
                    "rg --glob='*.md' ..", "find .. -name '*.java'",
                    # 매개변수 펼침·산술 안 `*`·`[`·`?`는 glob이 아니다
                    "cd ${f%/*}/..", "ls ${a[0]}/..", "ls $((i*2))/..", "ls \"${f%/*}\"/../x", "ls ${x:-?}/..",
                    # 닫히지 않은 따옴표도 예외 없이 빈 목록(판정 예외는 모든 Bash를 막는다)
                    "ls 'a */..", 'ls "a */..', "ls a\\"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.words(cmd), [], cmd)

    def test_glob_after_parameter_expansion_still_caught(self):
        self.assertEqual(self.words("ls ${D}/*/../x"), ["${D}/*/../x"])
        self.assertEqual(self.words("ls $((1+1))*/.."), ["$((1+1))*/.."])

    def test_reported_once_per_word_in_order(self):
        self.assertEqual(self.words("ls a/*/.. b/?/../c a/*/.."), ["a/*/..", "b/?/../c"])


class GitObjectReadTest(unittest.TestCase):
    """git `-C` 기준 자리·`<rev>:<경로>` 꼴. 합성 저장소(꼭대기 `.git`), cwd는 모듈 자리."""

    def setUp(self):
        import tempfile
        self.top = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(self.top, ".git"))
        self.mod = os.path.join(self.top, "svc/platform-services/alpha")
        os.makedirs(self.mod)
        os.makedirs(os.path.join(self.top, "svc/platform-services/beta/src/testFixtures"))
        self.deny = [f"Read(/{self.top}/svc/platform-services/beta/**)", f"Read(/{self.top}/svc/.agents/**)"]

    def r(self, cmd, cwd=None):
        return g.deny_read_hits(cmd, cwd or self.mod, self.deny)

    P = "svc/platform-services/beta/src/testFixtures/java/X.java"

    def test_alpha_w098_leak_command_is_blocked(self):
        """하위 에이전트가 41파일을 꺼낸 원문(자리만 합성 저장소로)."""
        cmd = (f"S=/tmp/sp; R={self.top}; mkdir -p $S/ptf; for f in $(git -C $R ls-tree -r --name-only dev/beta -- "
               "svc/platform-services/beta/src/testFixtures); do git -C $R show dev/beta:$f > $S/ptf/$(basename $f); "
               "done; ls $S/ptf | wc -l")
        self.assertTrue(self.r(cmd))

    def test_git_dash_c_is_the_base_of_path_arguments(self):
        for cmd in (f"git -C {self.top} ls-tree -r --name-only dev/beta -- svc/platform-services/beta/src/testFixtures",
                    f"R={self.top}; git -C $R ls-tree -r dev/beta -- svc/platform-services/beta",
                    f"git -C {self.top} archive dev/beta svc/platform-services/beta | tar -x -C /tmp/x",
                    f"git -C {self.top} log -p dev/beta -- svc/platform-services/beta",
                    f"git -C {self.top}/svc -C platform-services diff a b -- beta/src",
                    f"git -C {self.top}/svc show dev/beta:./platform-services/beta/build.conf.kts",
                    f"R={self.top}; echo $(git -C $R ls-tree -r dev/beta -- svc/platform-services/beta)"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.r(cmd), cmd)

    def test_git_dash_c_elsewhere_and_own_paths_pass(self):
        for cmd in (f"git -C {self.mod} ls-tree -r dev/beta -- svc/platform-services/beta",  # 모듈 자리 기준 — 없는 자리
                    "git ls-tree -r dev/beta -- svc/platform-services/beta",  # cwd(모듈) 기준
                    f"git -C {self.top} log --oneline -3", f"git -C {self.top} show dev/main:svc/platform-services/alpha/x",
                    "git show dev/main:./build.conf.kts"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.r(cmd), [], cmd)

    def test_dynamic_path_after_rev_is_blocked_for_object_readers(self):
        for cmd in ("git show dev/beta:$f", 'git show "dev/beta:$f"', "for f in a b; do git show dev/beta:$f; done",
                    "git cat-file -p dev/beta:`cat list`",
                    "git ls-tree -r --name-only dev/beta | xargs -I{} git show dev/beta:{}",
                    "git ls-tree -r --name-only dev/beta | while read f; do git show \"dev/beta:$f\"; done",
                    "git archive dev/beta:$d", "git diff dev/main:$a dev/beta:$a"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.r(cmd), cmd)

    def test_dynamic_rev_with_literal_path_still_judges_the_path(self):
        self.assertTrue(self.r(f"git show $c:{self.P}"))
        self.assertTrue(self.r(f'git show "$c":{self.P}'))
        self.assertEqual(self.r("git show $c:svc/platform-services/alpha/x"), [])

    def test_top_relative_forms(self):
        for cmd in (f"git show :0:{self.P}", f"git show :2:{self.P}",
                    "git log -p dev/beta -- ':/svc/platform-services/beta'",
                    "git log -p dev/beta -- ':(top)svc/platform-services/beta'",
                    "git log -p dev/beta -- ':(top,icase)svc/platform-services/beta'",
                    "git ls-tree -r --full-tree dev/beta svc/platform-services/beta"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.r(cmd), cmd)
        self.assertEqual(self.r("git log -- ':/svc/platform-services/alpha'"), [])

    def test_refspecs_and_non_object_commands_with_variables_pass(self):
        for cmd in ("git push origin $b:$b", "git fetch origin $b:$b", "git log --format=%H:%s", "echo dev/beta:$f",
                    "git config --get remote.$r.url"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.r(cmd), [], cmd)

    def test_unknown_dash_c_place_blocks_only_with_arguments(self):
        """`-C` 값을 셸이 실행 중에 정하면 경로 인자의 기준 자리를 몰라 막는다 — 인자 없는 하위 명령은 통과(구현하며 더함)."""
        self.assertTrue(self.r(f"git -C $X show dev/beta:{self.P}"))
        self.assertTrue(self.r("git -C \"$X\"/.. ls-tree -r dev/beta -- svc/platform-services/beta"))
        self.assertEqual(self.r("git -C $X status"), [])

    def test_without_deny_nothing_is_judged(self):
        self.assertEqual(g.deny_read_hits("git show dev/beta:$f", self.mod, []), [])

    def test_command_substitution_earlier_does_not_hide_later_git(self):
        """앞쪽 `$( … )`가 조각을 끊어 뒤 git 판정을 끄면 안 된다."""
        for cmd in ("for f in $(cat /tmp/l); do git show dev/beta:$f; done",
                    f"R={self.top}; for f in $(git -C $R log --name-only --format= -1 dev/beta); do git -C $R show dev/beta:$f; done",
                    "echo $(date); git show dev/beta:$f",
                    f"git -C $(pwd) show dev/beta:{self.P}"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.r(cmd), cmd)

    def test_substitution_sees_assignment_in_force_where_it_stands(self):
        """뒤에서 같은 이름을 다시 지정해도 `$( … )` 안은 막힌다."""
        self.assertTrue(self.r(f'R={self.top}; echo "$(git -C $R show dev/beta:{self.P})"; R=/tmp'))
        self.assertTrue(self.r(f'R={self.top}\necho "$(git -C $R show dev/beta:{self.P})"\nR=/tmp'))

    def test_unknown_place_with_rev_path_is_blocked(self):
        """`cd $D` 뒤 `<rev>:<상대 경로>`는 꼭대기를 몰라 막는다."""
        self.assertTrue(self.r(f"cd $D && git show dev/beta:{self.P}"))
        self.assertTrue(self.r(f"cd $D; git -C $X show dev/beta:{self.P}"))
        self.assertEqual(self.r("cd $D && git log --oneline -3"), [])

    def test_dynamic_pathspec_after_rev_is_blocked(self):
        """`<rev> -- $f` 꼴도 같은 결."""
        for cmd in (f"R={self.top}; for f in $(git -C $R diff --name-only dev/main dev/beta); do git -C $R log -p -1 dev/beta -- $f; done",
                    "git blame dev/beta -- $f", "git show abc123 -- $f", "git diff a b -- $f"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.r(cmd), cmd)
        self.assertEqual(self.r("git log -- $f"), [])

    def test_git_grep_pattern_is_not_a_path(self):
        self.assertEqual(self.r("git grep -e 'TODO:${' HEAD"), [])
        self.assertEqual(self.r("git grep 'a:$b' HEAD"), [])


class NeutralMessageTest(unittest.TestCase):
    """막는 글은 모듈 중립: 옛 결정·작업 번호를 싣지 않는다."""
    OLD = __import__("re").compile(r"W-0\d\d|\d{4}·(?:0042|0058|0071|0890)|(?:0042|0058|0071|0200|0870|0890|0900)[)·]")

    def test_reason_messages_carry_no_alpha_numbers(self):
        for cmd in ("echo ${x%y}", "cd $D && git commit -m x", "echo 'a", "git checkout x", "git reset --hard",
                    "git branch -D b", "git -c alias.x=y status", "git --config-env=alias.x=Y status", "git $x",
                    f"git -C {LEAD} commit -m x"):
            with self.subTest(cmd=cmd):
                why = g.reason(cmd, LEAD, cwd="/tmp") or ""
                self.assertTrue(why, cmd)
                self.assertIsNone(self.OLD.search(why), why)

    def test_read_hit_messages_carry_no_alpha_numbers(self):
        import tempfile
        top = os.path.realpath(tempfile.mkdtemp())
        deny = [f"Read(/{top}/secret/**)"]
        for cmd in ("echo 'a", "sh x.sh", "python3 -"):
            with self.subTest(cmd=cmd):
                found = " ".join(g.deny_read_hits(cmd, top, deny))
                self.assertTrue(found, cmd)
                self.assertIsNone(self.OLD.search(found), found)


class BodyDataBase(unittest.TestCase):
    """공통 자리: 리드 자리 `seat`(읽기·쓰기 deny), 작업 워크트리 `wt`(`mod/.agents/workflow` 쓰기 deny), 밖 `out`."""

    def setUp(self):
        import tempfile
        self.t = t = os.path.realpath(tempfile.mkdtemp())
        for d in ("seat/svc/tools", "wt/mod/.agents/workflow", "wt/mod/src", "out"):
            os.makedirs(os.path.join(t, d))
        self.seat, self.wt, self.out = (os.path.join(t, d) for d in ("seat", "wt", "out"))
        self.rules = [f"Read(/{self.seat}/**)", f"Edit(/{self.seat}/**)", f"Edit(/{self.wt}/mod/.agents/workflow/**)"]

    def r(self, cmd, cwd=None):
        return g.deny_read_hits(cmd, cwd or self.wt, self.rules, repo_top=self.wt)

    def w(self, cmd, cwd=None):
        return g.deny_write_hits(cmd, cwd or self.wt, self.rules, repo_top=self.wt)

    def script(self, rel, body):
        path = os.path.join(self.t, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body)
        return path


class BodyDataTest(BodyDataBase):
    """본문 글자의 데이터 자리(데이터 호출 인자, 데이터 자리에서만 쓰는 상수)는 경로가 아니다."""

    def test_data_positions_pass_read_and_write(self):
        s, o = self.seat, self.out
        for cmd in (f"python3 - <<'EOF'\nSEAT = '{s}'\nprint(SEAT)\nEOF",  # 시험 상수
                    f"python3 - <<'EOF'\nSEAT = '{s}'\nassert 'x'.startswith(SEAT) or True\nprint(f'{{SEAT}}/svc')\nEOF",
                    f"python3 -c \"import sys; assert sys.argv[1].startswith('{s}')\" x",
                    f"python3 - <<'EOF'\nimport json\nopen('{o}/a.json','w').write(json.dumps({{'lead': '{s}'}}))\nEOF",
                    f"python3 - <<'EOF'\nimport pathlib\npathlib.Path('{o}/t.py').write_text('SEAT = \"{s}\"')\nEOF",
                    f"python3 -c \"print('{s}/svc/tools/x')\"",
                    f"python3 -c \"print(f'{s}/x')\"",  # 붙은 문자열 머리(STRING_PREFIX)
                    f"python3 -c \"print(sorted(['{s}/x']))\"",  # 감싸기 호출 건넘(PASS_CALLS)
                    f"node -e \"console.log('{s}/x')\""):
            self.assertEqual(self.r(cmd), [], cmd)
            self.assertEqual(self.w(cmd), [], cmd)

    def test_alpha_test_constant_script_passes(self):
        """test_open.py 꼴: 상수를 assertEqual·assertIn·f-string 안에서만 쓴다( 실측)."""
        s = self.seat
        body = (f'import unittest\nSEAT = "{s}"\nHWT = "{s}-P-099"\n'
                'class T(unittest.TestCase):\n    def test_a(self):\n        places = {"seat": "x"}\n'
                '        self.assertEqual(places["seat"], SEAT)\n'
                '        self.assertIn(f"Edit(/{SEAT}/**)", ["x"])\n        self.assertEqual(HWT, HWT)\n'
                '        self.assertTrue(any(f"{SEAT}/x" in c for c in []) or True)\n'  # 감싸기 호출(PASS_CALLS)
                '        self.assertEqual(SEAT2, SEAT2)\n'
                f'SEAT2 = f"{{SEAT}}-x"\n')  # 데이터 상수에만 쓰이는 상수(고정점)
        path = self.script("wt/mod/.agents/workflow/session/test_x.py", body)
        rel = os.path.relpath(path, os.path.join(self.wt, "mod"))
        for cmd, cwd in ((f"python3 {path}", None), (f"cd {self.wt}/mod && python3 {rel}", None), (f"python3 {rel}", f"{self.wt}/mod")):
            self.assertEqual(self.r(cmd, cwd), [], cmd)
            self.assertEqual(self.w(cmd, cwd), [], cmd)

    def test_real_uses_stay_blocked(self):
        s = self.seat
        for cmd in (f"python3 - <<'EOF'\nSEAT = '{s}'\nprint(open(SEAT + '/x').read())\nEOF",
                    f"python3 - <<'EOF'\nP = '{s}/x'\nprint(P)\nprint(open(P).read())\nEOF",
                    f"python3 -c \"print(open('{s}/x').read())\"",
                    f"python3 -c \"import subprocess; subprocess.run(['cat', '{s}/x'])\"",
                    f"python3 - <<'EOF'\nfor p in ['{s}/x']:\n    print(open(p).read())\nEOF",
                    f"python3 -c \"print(open(str('{s}/x')).read())\"",
                    # ~4: `;` 지정·컴프리헨션·f-string 식·짝 없는 괄호
                    f"python3 -c \"P='a'; x='{s}/x'; print(P); print(open(x).read())\"",
                    f"python3 -c \"print([open(p).read() for p in ['{s}/x']])\"",
                    f"python3 -c \"print(any(open(p) for p in ['{s}/x']))\"",
                    f"python3 -c \"print({{p: open(p).read() for p in ('{s}/x',)}})\"",
                    f"python3 - <<'EOF'\nSEAT = '{s}/x'\nprint(f\"{{open(SEAT).read()}}\")\nEOF",
                    f"python3 - <<'EOF'\n# print(\nx = '{s}/x'\nprint(x)\nprint(open(x).read())\nEOF",
                    f"python3 -c \"import zipfile; zf = zipfile.ZipFile('/tmp/o.zip', 'w'); zf.write('{s}/x')\"",
                    f"ruby -e \"puts(File.read '{s}/x')\"",  # 괄호 없는 안쪽 호출
                    f"python3 - <<'EOF'\nSEAT = '{s}/x'\nprint(SEAT)\nprint(open(globals()['SEAT']).read())\nEOF"):  # 동적 이름(Minor)
            self.assertTrue(self.r(cmd), cmd)
        for cmd in (f"python3 -c \"open('{s}/x','w')\"",
                    f"python3 -c \"import pathlib; pathlib.Path('{s}/x').write_text('y')\"",
                    f"python3 - <<'EOF'\nSEAT = '{s}'\nprint(SEAT)\nopen(SEAT + '/x', 'w')\nEOF",
                    f"python3 - <<'EOF'\nimport json\njson.dump({{}}, open('{s}/x', 'w'))\nEOF",
                    f"python3 -c \"import shutil; shutil.copy('a', '{s}/x')\"",
                    f"ruby -e \"File.write('{s}/x', 'y')\"", f"ruby -e \"IO.write('{s}/x', 'y')\"",  # 경로 받는 클래스(Important 1)
                    f"bun -e \"Bun.write('{s}/x', 'y')\"", f"ruby -e \"puts(File.write '{s}/x', 'y')\"",
                    f"python3 -c \"import os; print(os.system('touch {s}/x'))\"",  # 셸 문자열 판정 그대로
                    f"python3 -c \"P='a'; x='{s}/x'; print(P); open(x,'w').write('y')\"",
                    f"python3 - <<'EOF'\nSEAT = '{s}/x'\nprint(f\"{{open(SEAT,'w').write('y')}}\")\nEOF",
                    f"python3 - <<'EOF'\n# print(\nx = '{s}/x'\nprint(x)\nopen(x, 'w')\nEOF"):
            self.assertTrue(self.w(cmd), cmd)


class BodyDataSpeedTest(BodyDataBase):
    """데이터 상수 고정점이 지정 사슬에서 제곱으로 늘지 않는다(훅 시간)."""

    def test_long_assignment_chain_is_fast(self):
        import time
        lines = [f"v0 = '{self.seat}/x'"] + [f'v{i} = f"{{v{i - 1}}}-x"' for i in range(1, 4000)] + ["open(v3999, 'w')"]
        body = "\n".join(lines)
        start = time.monotonic()
        g._data_starts(body)
        self.assertLess(time.monotonic() - start, 2.0)


class ScriptFileWriteTest(BodyDataBase):
    """인터프리터 스크립트 파일 본문도 인라인과 같은 쓰기 판정."""

    def test_new_script_writing_deny_is_blocked(self):
        s = self.seat
        bad = self.script("out/w.py", f"open('{s}/svc/tools/x', 'w').write('y')\n")
        bad2 = self.script("out/w2.py", f"import os\nos.remove('{self.wt}/mod/.agents/workflow/s.json')\n")
        for cmd in (f"python3 {bad}", f"python3 -I {bad}", f"cd {self.out} && python3 w.py", f"python3 {bad2}",
                    f"cat > {self.out}/n.py <<'E'\nopen('{s}/x', 'w')\nE\npython3 {self.out}/n.py"):
            self.assertTrue(self.w(cmd), cmd)

    def test_reads_outside_writes_and_data_pass(self):
        s, o = self.seat, self.out
        ok = [self.script("out/r.py", f"print(open('{o}/x').read())\n"),
              self.script("out/o.py", f"open('{o}/x', 'w').write('{s}')\n"),
              self.script("out/c.py", "import os, sys\nHERE = os.path.dirname(__file__)\nopen(os.path.join(HERE, 'y'), 'w')\n")]
        for path in ok:
            self.assertEqual(self.w(f"python3 {path}"), [], path)


class CdRelativeTest(BodyDataBase):
    """`cd <자리> && …` 뒤 상대 경로는 cd 자리 기준(walk)."""

    def test_relative_after_cd(self):
        self.script("seat/svc/tools/t.py", "print(1)\n")
        self.script("wt/mod/src/t.py", "print(1)\n")
        self.assertTrue(self.r(f"cd {self.seat}/svc && cat tools/t.py"))
        self.assertTrue(self.r(f"cd {self.t} && cd seat && python3 svc/tools/t.py"))
        self.assertTrue(self.w(f"cd {self.wt}/mod && echo x > .agents/workflow/s.json"))
        self.assertEqual(self.r(f"cd {self.wt}/mod && python3 src/t.py"), [])
        self.assertEqual(self.r("cd mod && python3 src/t.py"), [])
        self.assertEqual(self.w(f"cd {self.wt}/mod && echo x > src/y"), [])


class InterpreterGitTest(unittest.TestCase):
    """인터프리터 본문(인라인·here-string·heredoc·스크립트 파일)의 git 쓰기 하위 명령 글자를 막는다.
    git 호출 꼴(같은 묶음 안 `git` 글자 뒤 하위 명령 글자, 셸 문자열·백틱의 `git <하위>`, 하이픈 든 하위 명령 글자)만 보고 데이터 자리는 뺀다."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def script(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(body)
        return path

    def blocked(self, cmd):
        return g.reason(cmd, LEAD, self.tmp) is not None

    def test_git_writes_in_interpreter_bodies_are_blocked(self):
        c406 = self.script("split.py", 'import subprocess\nd = "/w"\nsubprocess.run(["git", "-C", d, "branch", "-f", "w", "HEAD"], check=True)\n')
        plumbing = self.script("plumb.py", 'import subprocess\nGIT = ["git"]\nt = subprocess.check_output(GIT + ["commit-tree", "abc", "-m", "x"])\n'
                                           'subprocess.run(GIT + ["update-ref", "refs/heads/x", t])\n')
        node = self.script("n.js", "require('child_process').execSync('git push origin x')\n")
        shebang = self.script("run", '#!/usr/bin/env python3\nimport os\nos.system("git reset --soft HEAD~1")\n')
        os.chmod(shebang, 0o755)
        for cmd in ("python3 -c 'import subprocess; subprocess.run([\"git\", \"checkout\", \"x\"])'",
                    f"python3 - <<'E'\nimport subprocess\nsubprocess.run(['git', 'cherry-pick', 'abc'])\nE",
                    f"python3 {c406}", f"python3 {plumbing}", f"node {node}", shebang,
                    "python3 -c \"import os; os.system('git rebase main')\"",
                    "perl -e 'print `git rebase main`'",
                    "python3 <<< 'import subprocess; subprocess.run([\"git\", \"switch\", \"x\"])'",
                    f"cat > {self.tmp}/m.py <<'E'\nimport subprocess\nsubprocess.run(['git', 'stash'])\nE\npython3 {self.tmp}/m.py",
                    "python3 -c \"import subprocess as s; s.run(['/usr/bin/git', 'reset', 'HEAD~1'])\"",
                    "ruby -e 'system(\"git\", \"filter-branch\", \"x\")'",
                    "python3 -c 'import subprocess; subprocess.run([\"git\", \"-c\", \"alias.co=checkout\", \"co\", \"x\"])'"):
            self.assertTrue(self.blocked(cmd), cmd)

    def test_shell_bodies_and_glued_operators_are_blocked(self):
        """·2: 셸 본문(heredoc·here-string·스크립트 파일·셸 shebang 실행 파일)의 git도 셸 판정으로, 붙여 쓴 연산자도 나눈다."""
        sh_file = self.script("s.sh", "cd /tmp\ngit checkout main\n")
        sh_exec = self.script("sx", "#!/bin/bash\ngit branch -f w HEAD\n")
        os.chmod(sh_exec, 0o755)
        for cmd in ("bash <<'E'\ngit checkout x\nE", f"bash {sh_file}", f". {sh_file}", f"sh {sh_file}", sh_exec,
                    "bash <<< 'git reset --hard'",
                    f"cat > {self.tmp}/n.sh <<'E'\ngit stash\nE\nbash {self.tmp}/n.sh",
                    "python3 -c 'import os; os.system(\"true&&git checkout x\")'",
                    "python3 -c 'import os; os.system(\"cd /tmp;git checkout x\")'",
                    "python3 -c 'import os; os.system(\"git log|git checkout x\")'"):
            self.assertTrue(self.blocked(cmd), cmd)

    def test_shell_bodies_that_only_read_pass(self):
        ok = self.script("r.sh", 'x="${HOME#/}"\ngit status\ngit log --oneline -1\n')
        for cmd in (f"bash {ok}", "bash <<'E'\ngit diff\nE", "sh -c 'echo hi'"):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_message_points_to_lead(self):
        found = g.reason("python3 -c 'import subprocess; subprocess.run([\"git\", \"checkout\", \"x\"])'", LEAD, self.tmp)
        self.assertIn("[막힘]", found)
        self.assertIn("checkout", found)

    def test_reads_data_and_flow_scripts_pass(self):
        state = self.script("state.py", 'import subprocess\ncwd = "."\n'
                                        'b = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True).stdout\n')
        order = self.script("order.py", 'import subprocess\nORDER = ("req", "plan", "merge")\nsubprocess.run(["git", "log", "--format=%s"])\n')
        for cmd in ("python3 -c 'print(\"git checkout x\")'",
                    "python3 -c 'import subprocess; subprocess.run([\"git\", \"log\", \"--format=%s\"])'",
                    "python3 -c 'import subprocess; subprocess.run([\"git\", \"commit\", \"-m\", \"x\"])'",
                    f"python3 {state}", f"python3 {order}",
                    # 작업 세션이 부르는 이 플러그인의 흐름 명령(입구 seam 본문)
                    f"python3 {testing.SEAM} status P-001", f"python3 {testing.SEAM} inspect P-001",
                    f"python3 {testing.SEAM} base P-001", f"python3 {testing.SEAM} carryover",
                    f"{testing.SEAM} inspect P-001", "seam inspect P-001", "seam carryover",  # 실행 권한 꼴·짧은 이름 꼴(막지 않는다)
                    "python3 -m unittest discover -s plugins/tailoring/tests",
                    "python3 -c 'msg = \"git push\"; print(msg)'"):
            self.assertFalse(self.blocked(cmd), cmd)


class QuotedHeredocTest(unittest.TestCase):
    """따옴표 heredoc(`<<'E'`) 본문은 셸이 펼치지 않으니 `$( … )`·백틱 안을 명령으로 보지 않는다.
    따옴표 없는 heredoc 본문은 셸이 실제로 돌리니 그대로 본다."""

    def blocked(self, cmd):
        return g.reason(cmd, LEAD, "/tmp") is not None

    def test_quoted_heredoc_text_passes(self):
        for cmd in ("cat >> notes.md <<'E'\n- 막힘: `cd $W && git add -A` 뒤 `git commit`\nE",
                    "cat > f.md <<'E'\nR=$(git -C $X push)\nE",
                    'cat > f.md <<"E"\n`git checkout x`\nE',
                    "cat >> f.md <<-'E'\n\t`git push`\n\tE"):
            self.assertFalse(self.blocked(cmd), cmd)

    def test_unquoted_and_shell_bodies_stay_blocked(self):
        for cmd in ("cat >> notes.md <<E\n- `cd $W && git add -A`\nE",
                    "cat > f.md <<E\nR=$(git push)\nE",
                    "bash <<'E'\ngit checkout x\nE",
                    "cat > f.md <<'E'\nx\nE\necho `git push`",
                    "echo \"<<'E'\"\necho $(git push)\nE"):  # : 따옴표 안 `<<'E'`는 heredoc이 아니다
            self.assertTrue(self.blocked(cmd), cmd)


class PatchBase(unittest.TestCase):
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.t, True)
        for r in ("me", "other"):
            for d in (".git", "deny", "x"):
                os.makedirs(os.path.join(self.t, r, d))
            open(os.path.join(self.t, r, "deny", "s.json"), "w").close()
        self.me, self.other = os.path.join(self.t, "me"), os.path.join(self.t, "other")

    def put(self, path, body):
        with open(path, "w") as f:
            f.write(body)

    def w(self, cmd, rules, cwd=None):
        return g.deny_write_hits(cmd, cwd or self.me, rules, repo_top=self.me)


class GitApplyRootTest(PatchBase):
    """git apply 패치 경로는 -C·cd·--work-tree로 옮긴 저장소 꼭대기 기준."""

    def setUp(self):
        super().setUp()
        for r in (self.me, self.other):
            self.put(os.path.join(r, "p.diff"), DIFF)
            self.put(os.path.join(r, "x", "p.diff"), DIFF)
        self.other_deny = [f"Edit(/{self.other}/deny/**)"]
        self.me_deny = [f"Edit(/{self.me}/deny/**)"]

    def test_other_repo_deny_blocks(self):
        o = self.other
        for cmd in (f"git -C {o} apply p.diff", f"git -C {o}/x apply p.diff", f"cd {o} && git apply p.diff",
                    f"git -C {o} apply {o}/p.diff", f"git --work-tree={o} apply {o}/p.diff", f"GIT_WORK_TREE={o} git apply {o}/p.diff"):
            self.assertTrue(self.w(cmd, self.other_deny, cwd=os.path.join(self.me, "x")), cmd)

    def test_other_repo_does_not_borrow_hook_repo_deny(self):
        o = self.other
        for cmd in (f"git -C {o} apply p.diff", f"cd {o} && git apply p.diff"):
            self.assertEqual(self.w(cmd, self.me_deny, cwd=os.path.join(self.me, "x")), [], cmd)
        self.assertTrue(self.w("git apply p.diff", self.me_deny, cwd=os.path.join(self.me, "x")))  # 제 저장소는 그대로
        for cmd in (f"GIT_DIR={self.me}/.git git apply {self.me}/p.diff", f"GIT_DIR={self.me}/.git git apply p.diff"):
            self.assertTrue(self.w(cmd, self.me_deny), cmd)  # : GIT_DIR은 뿌리가 아니다


class PatchTargetTest(PatchBase):
    """patch 쓰기 대상(입력 -i·<·heredoc, -d·-p·-o·originalfile)을 Edit deny와 대조."""

    def setUp(self):
        super().setUp()
        self.put(os.path.join(self.me, "p.diff"), DIFF)
        self.put(os.path.join(self.me, "p0.diff"), "--- deny/s.json\n+++ deny/s.json\n@@ -0,0 +1 @@\n+x\n")
        self.put(os.path.join(self.me, "ok.diff"), OK_DIFF)
        self.put(os.path.join(self.me, "git.diff"), "diff --git a/deny/s.json b/deny/s.json\n--- a/deny/s.json\n+++ b/deny/s.json\n")
        self.rules = [f"Edit(/{self.me}/deny/**)", f"Edit(/{self.other}/deny/**)"]

    def test_blocks(self):
        o = self.other
        for cmd in ("patch -p1 < p.diff", "patch -p1 -i p.diff", "patch -p1 --input=p.diff", "patch -p 1 -i p.diff",
                    "patch --strip=1 < p.diff", "patch -p0 < p0.diff", "patch < p0.diff", "patch -p1 < git.diff",
                    f"patch -d {o} -p1 < {self.me}/p.diff", f"patch --directory={o} -p1 -i {self.me}/p.diff",
                    f"cd {o} && patch -p1 < {self.me}/p.diff", "patch -p1 <<'E'\n" + DIFF + "E",
                    "patch -o deny/o.json -p1 < ok.diff", "patch --output=deny/o.json -p1 < ok.diff",
                    "patch deny/s.json ok.diff", "patch deny/s.json < ok.diff", "patch -r deny/rej -p1 < ok.diff",
                    "git diff | patch -p1", "cat p.diff | patch -p1", "patch -p1", "patch -p1 -i nope.diff",
                    "patch -p1 < $P", "patch -pX < p.diff", "/usr/bin/patch -p1 < p.diff", "gpatch -p1 < p.diff",
                    "sh -c 'patch -p1 < p.diff'", "patch -R -p1 < p.diff",
                    "patch -Np1 < p.diff", "patch -sp1 -i p.diff", "patch -Ni p.diff -p1", "patch -x 1 -p1 < p.diff",
                    "patch -fsp1 -i p.diff"):  # : 묶음 짧은 옵션·-x
            self.assertTrue(self.w(cmd, self.rules), cmd)

    def test_passes(self):
        for cmd in ("patch -p1 < ok.diff", "patch -p1 -i ok.diff", "patch --dry-run -p1 < p.diff", "patch -C -p1 < p.diff",
                    "patch --check -p1 < p.diff", "patch -p1 -d x < p.diff", "patch -p2 < p.diff", "patch x/q < p.diff",
                    "patch -p1 <<'E'\n" + OK_DIFF + "E", "echo patch -p1 deny/s.json", "patch --version"):
            self.assertEqual(self.w(cmd, self.rules), [], cmd)


class SlashWordsTest(unittest.TestCase):
    """경로 이름 글자 없는 낱말(`/`·`//`·`/**`·`*/`)은 본문 쓰기 경로 후보가 아니다."""

    def setUp(self):
        import tempfile
        self.t = t = os.path.realpath(tempfile.mkdtemp())
        for d in ("svc/tools/guard-hooks", "svc/mod/x", "out"):
            os.makedirs(os.path.join(t, d))
        self.cwd = os.path.join(t, "svc/mod/x")
        self.rules = [f"Edit(/{t}/svc/tools/**)"]

    def w(self, cmd, cwd=None):
        return g.deny_write_hits(cmd, cwd or self.cwd, self.rules, repo_top=self.t)

    def test_slash_only_words_pass(self):
        """꼴: 쓰기 의도 + 나무 낱말(find·walk·glob) + 나누기·주석 조각, 쓰는 파일은 허용 자리."""
        for cmd in ("python3 - <<'E'\nimport pathlib\np = pathlib.Path('a.py')\nn = len('ab') / 2  # find\np.write_text('x')\nE",
                    "python3 - <<'E'\nimport os\nfor r, d, f in os.walk('.'):\n    pass\nk = 7 // 2\nopen('a.txt', 'w').write('x')\nE",
                    "python3 - <<'E'\nimport glob, pathlib\np = pathlib.Path('T.java')\n/** doc */\nprint(glob.glob('*.java'))\np.write_text('x')\nE",
                    "python3 - <<'E'\nimport pathlib\np = pathlib.Path('T.java')\ns = p.read_text().replace('/**', '/*')  # find\np.write_text(s)\nE",
                    "python3 - <<'E'\nimport pathlib\np = pathlib.Path('T.java')\ns = p.read_text().replace('*/', '/')  # walk\np.write_text(s)\nE",
                    "python3 -c \"import os; [os.walk('.')]; open('a', 'w').write(str(4 / 2))\""):
            self.assertEqual(self.w(cmd), [], cmd)

    def test_script_file_slash_strings_pass(self):
        """스크립트 파일 갈래: `'/**'`는 글롭 펼침 한도로 막던 꼴 — 한도를 줄여 옛 코드가 막는 것을 보인다."""
        path = os.path.join(self.t, "out", "s.py")
        with open(path, "w") as f:
            f.write("import glob\nfor p in glob.glob('/**'):\n    pass\nopen('/tmp/gx26-x', 'w').write('/')\n")
        old = g.WALK_LIMIT
        g.WALK_LIMIT = 2
        try:
            self.assertEqual(self.w(f"python3 {path}"), [])
        finally:
            g.WALK_LIMIT = old

    def test_relative_globs_under_deny_parent_stay_blocked(self):
        """동작 I1: 이름 글자 없는 상대 글롭(`*`·`*/*`·`**`)은 뿌리 꼴이 아니라 경로 후보로 남는다."""
        base = os.path.join(self.t, "svc")
        for cmd in ("python3 -c \"import glob,shutil; [shutil.rmtree(p) for p in glob.glob('*/*')]\"",
                    "python3 -c \"import glob,shutil; [shutil.rmtree(p) for p in glob.glob('*')]\"",
                    "python3 - <<'E'\nimport glob\nfor p in glob.glob('**', recursive=True):\n    open(p, 'w')\nE"):
            self.assertTrue(self.w(cmd, base), cmd)

    def test_real_deny_writes_stay_blocked(self):
        t = self.t
        for cmd in (f"python3 - <<'E'\nn = 3 / 2  # find\nopen('{t}/svc/tools/x.py', 'w').write('y')\nE",
                    "python3 - <<'E'\nimport pathlib\nn = 3 / 2\npathlib.Path('../../tools/x').write_text('y')\nE",
                    "python3 - <<'E'\nk = 7 // 2  # walk\nopen('../../tools/' + 'guard-hooks/x', 'w')\nE",
                    "python3 - <<'E'\nimport os\nopen(os.path.join('../..', 'tools', 'x'), 'w')  # /**\nE",
                    f"python3 -c \"open('{t}/svc/tools/x', 'w').write(str(1 / 2))\""):
            self.assertTrue(self.w(cmd), cmd)
        path = os.path.join(t, "out", "d.py")
        with open(path, "w") as f:
            f.write(f"x = 1 / 2\nopen('{t}/svc/tools/x.py', 'w').write('/**')\n")
        self.assertTrue(self.w(f"python3 {path}"))

    def test_code_path_words_drop_nameless_words(self):
        words = g._code_path_words("n = 3 / 2 // 1\n/** c */\nopen('/', 'w'); x = '/**'; y = './a'; z = '~/b'; q = a/b\n")
        for w in ("/", "//", "/**"):  # 뿌리 꼴만 뺀다
            self.assertNotIn(w, words)
        for w in ("./a", "~/b", "a/b", "*/"):  # `*/`는 상대 글롭이라 남는다( 동작 I1)
            self.assertIn(w, words)


class HomeRepoBase(unittest.TestCase):
    """합성 홈(`<t>/home/me`)과 합성 저장소(`<t>/repo`, 꼭대기 `.git`)."""

    def setUp(self):
        from unittest import mock
        self.t = t = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t, True)
        self.home = os.path.join(t, "home", "me")
        self.other = os.path.join(t, "home", "nouserx131")  # 이 맥에 없는 사용자 — 홈 뿌리(`<t>/home`) 아래로 푼다
        self.top = os.path.join(t, "repo")
        for d in (".ssh", ".config/my-claude"):
            os.makedirs(os.path.join(self.home, d))
        os.makedirs(os.path.join(self.other, ".config", "my-claude"))
        os.makedirs(os.path.join(self.top, ".git"))
        os.makedirs(os.path.join(self.top, ".agents"))
        os.makedirs(os.path.join(self.top, "svc", "platform-services", "alpha"))
        os.makedirs(os.path.join(self.top, "svc", "platform-services", "build"))
        os.makedirs(os.path.join(self.top, "svc", "tools", "remote"))
        p = mock.patch.dict(os.environ, {"HOME": self.home})
        p.start()
        self.addCleanup(p.stop)


class TildeUserTest(HomeRepoBase):
    """`~<사용자>/…`를 그 사용자 홈 절대 경로로 풀어 deny와 대조한다 — 이 맥에 없는 사용자도 홈 뿌리 아래로."""

    def rules(self):
        return [f"Read(/{self.other}/.config/my-claude/**)", f"Edit(/{self.other}/.config/my-claude/**)"]

    def test_unknown_user_tilde_read_is_blocked(self):
        for cmd in ("cat ~nouserx131/.config/my-claude/t", "grep -n x ~nouserx131/.config/my-claude/t",
                    "cd ~nouserx131/.config && cat my-claude/t", "cd ~nouserx131 && cat .config/my-claude/t"):
            with self.subTest(cmd=cmd):
                self.assertTrue(g.deny_read_hits(cmd, self.top, self.rules()), cmd)

    def test_unknown_user_tilde_write_is_blocked(self):
        for cmd in ("echo x > ~nouserx131/.config/my-claude/t", "cp /tmp/a ~nouserx131/.config/my-claude/t"):
            with self.subTest(cmd=cmd):
                self.assertTrue(g.deny_write_hits(cmd, self.top, self.rules()), cmd)

    def test_unknown_user_outside_deny_passes(self):
        for cmd in ("cat ~nouserx131/.config/other", "ls ~nouserx131"):
            with self.subTest(cmd=cmd):
                self.assertEqual(g.deny_read_hits(cmd, self.top, self.rules()), [], cmd)

    def test_tilde_plus_is_cwd(self):
        """`~+`는 셸이 `$PWD`로 푼다 — 기준 자리로 대조한다."""
        rules = [f"Read(/{self.home}/.ssh/**)"]
        for cmd in ("cat ~+/.ssh/config", "cd ~ && cat ~+/.ssh/config"):
            with self.subTest(cmd=cmd):
                self.assertTrue(g.deny_read_hits(cmd, self.home, rules), cmd)
        self.assertEqual(g.deny_read_hits("cat ~+/x", self.home, rules), [])

    def test_tilde_plus_with_unknown_base_is_relative(self):
        """동작 Minor 1: 기준 자리를 모를 때(`cd $D` 뒤) `~+`는 모르는 상대 경로다 — 뿌리 `/`로 풀지 않는다."""
        rules = [f"Edit(/{self.top}/.agents/**)"]
        self.assertTrue(g.deny_write_hits("cd $D && echo x > ~+/a", self.top, rules))  # 모르는 자리 상대 쓰기는 막음
        self.assertIsNone(g.moved_base(["cd", "~+"], None))
        self.assertEqual(g.moved_base(["cd", "~+"], self.top), self.top)

    def test_this_machine_user_tilde_still_resolves_by_pwd(self):
        import pwd
        me = pwd.getpwuid(os.getuid())
        rules = [f"Read(/{os.path.realpath(me.pw_dir)}/x131-none/**)"]
        self.assertTrue(g.deny_read_hits(f"cat ~{me.pw_name}/x131-none/x", self.top, rules))

    def test_expanduser_helper(self):
        self.assertEqual(g._expanduser("~nouserx131/a"), os.path.join(self.other, "a"))
        self.assertEqual(g._expanduser("~nouserx131"), self.other)
        self.assertEqual(g._expanduser("~/a"), os.path.join(self.home, "a"))
        self.assertEqual(g._expanduser("~+/a"), "./a")
        self.assertEqual(g._expanduser("~+"), ".")
        for w in ("~", "a/~b", "~$X/a", "~a b", "~-/x", "~-", "~+x"):
            with self.subTest(w=w):
                self.assertEqual(g._expanduser(w), os.path.expanduser(w))


class RevPathTest(HomeRepoBase):
    """`<rev>:<경로>`는 꼭대기 기준, `<rev>:./`·`<rev>:../`는 cwd(`cd`·`-C` 뒤 자리) 기준 — git과 같다."""

    def rules(self):
        return [f"Read(/{self.top}/svc/platform-services/alpha/**)", f"Read(/{self.top}/.agents/**)"]

    def r(self, cmd, cwd):
        return g.deny_read_hits(cmd, cwd, self.rules())

    def test_dot_slash_is_cwd_relative(self):
        svc = os.path.join(self.top, "svc")
        for cmd, cwd in (("git show HEAD:./platform-services/alpha/x", svc),
                         ("git show HEAD:./alpha/x", os.path.join(svc, "platform-services")),
                         ("cd platform-services && git show HEAD:./alpha/x", svc),
                         ("git -C platform-services show HEAD:./alpha/x", svc),
                         ("git show HEAD:../.agents/x", svc), ("git cat-file -p HEAD:./../.agents/x", svc),
                         ("git show :./platform-services/alpha/x", svc), ("git show dev/main:./alpha/x",
                                                                                os.path.join(svc, "platform-services"))):
            with self.subTest(cmd=cmd, cwd=cwd):
                self.assertTrue(self.r(cmd, cwd), cmd)

    def test_plain_rev_path_is_top_relative(self):
        svc = os.path.join(self.top, "svc")
        for cmd in ("git show HEAD:svc/platform-services/alpha/x", "git show HEAD:.agents/x",
                    "git -C platform-services show HEAD:svc/platform-services/alpha/x"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.r(cmd, svc), cmd)
        for cmd in ("git show HEAD:platform-services/alpha/x", "git show HEAD:alpha/x"):  # 꼭대기 기준 — deny 밖
            with self.subTest(cmd=cmd):
                self.assertEqual(self.r(cmd, os.path.join(svc, "platform-services") if "HEAD:alpha" in cmd else svc),
                                 [], cmd)


class HomeDotReadTest(HomeRepoBase):
    """홈 `~/.ssh` Read deny는 셸 읽기도 막는다 — 명령 이름과 상관없이 경로 인자를 대조(새 판정 없음, 고정만)."""

    def rules(self):
        return [f"Read(/{self.home}/.ssh/**)", f"Edit(/{self.home}/.ssh/**)"]

    def test_shell_reads_of_ssh_are_blocked(self):
        for cmd in ("cat ~/.ssh/config", "head -1 ~/.ssh/id_ed25519", "tail -n 3 ~/.ssh/known_hosts", "less ~/.ssh/config",
                    "grep Host ~/.ssh/config", "xxd ~/.ssh/k", "base64 < ~/.ssh/k", "cp ~/.ssh/k /tmp/k",
                    "cat $HOME/.ssh/config", 'cat "${HOME}/.ssh/config"', "cd ~ && cat .ssh/config", "cd ~/.ssh; cat config",
                    "ls ~/.ssh", "find ~/.ssh -type f", "H=~/.ssh; cat $H/config", 'cat ~/".ssh"/config',
                    f"cat {self.home}/.ssh/config", "cat ~me/.ssh/config",
                    f"python3 -c \"print(open('{self.home}/.ssh/config').read())\""):
            with self.subTest(cmd=cmd):
                self.assertTrue(g.deny_read_hits(cmd, self.top, self.rules()), cmd)

    def test_reads_outside_ssh_pass(self):
        for cmd in ("cat ~/.sshx", "ls ~/.config", "find ~ -name id_rsa", "grep -n ssh README.md"):
            with self.subTest(cmd=cmd):
                self.assertEqual(g.deny_read_hits(cmd, self.top, self.rules()), [], cmd)


class DotDotRunTest(HomeRepoBase):
    """글자 아닌 인자 뒤에 이어진 `..`만 든 런(`join(HERE, "..", "..")`)은 cwd 기준 쓰기 후보가 아니다 —
    홀로 선 `'..'`·`Path('..')`·이름 마디가 붙은 상대 쓰기·훑기 뒤 쓰기는 그대로 막는다."""

    def setUp(self):
        super().setUp()
        self.cwd = os.path.join(self.top, "svc", "tools", "remote")
        self.rules = [f"Edit(/{self.top}/svc/platform-services/build/**)"]

    def w(self, cmd, cwd=None):
        return g.deny_write_hits(cmd, cwd or self.cwd, self.rules, repo_top=self.top)

    NESTED = ("python3 - <<'PY'\nimport glob\nfrom pathlib import Path\np = Path('lead_token.py')\nsrc = p.read_text()\n"
              "src = src.replace('X = 1', 'TOP = os.path.join(HERE, \"..\", \"..\", \"..\")')\np.write_text(src)\nPY")
    TRIPLE = ("python3 - <<'PY'\nfrom pathlib import Path\np = Path('lead_token.py')\nnew = '''\n"
              "HERE = os.path.dirname(os.path.abspath(__file__))\nTOP = os.path.join(HERE, \"..\", \"..\", \"..\")\n"
              "for f in glob.glob(os.path.join(TOP, 'x')):\n    pass\n'''\np.write_text(p.read_text().replace('# mark', new))\nPY")

    def test_dotdot_text_passes(self):
        for cmd in (self.NESTED, self.TRIPLE):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.w(cmd), [], cmd)

    def test_dotdot_run_after_dynamic_arg_is_dropped(self):
        words = g._code_path_words("x = os.path.join(HERE, '..', '..'); y = '../a'")
        for w in ("..", "../.."):
            self.assertNotIn(w, words)
        self.assertIn("../a", words)
        words = g._code_path_words("x = os.path.join('..', '..'); z = f(a[0], '..', 'x')")
        self.assertIn("../..", words)  # 글자 인자로 시작한 런은 그대로
        self.assertIn("../x", words)  # 이름 마디가 붙은 런은 글자 아닌 인자 뒤라도 그대로
        self.assertIn("..", g._code_path_words("os.path.join(HERE, '..'); p = Path('..')"))  # 다른 자리에 홀로 서면 남는다
        self.assertTrue(g._dotdot_only("../..") and g._dotdot_only("..") and g._dotdot_only("../../"))
        for w in ("../a", "a/..", "...", "./..", ".", "~/..", "/.."):
            with self.subTest(w=w):
                self.assertFalse(g._dotdot_only(w), w)

    def test_named_relative_writes_stay_blocked(self):
        for cmd in ("python3 -c \"open('../../platform-services/build/x', 'w')\"",
                    "python3 -c \"import os; open(os.path.join('..', '..', 'platform-services', 'build', 'x'), 'w')\"",
                    "python3 - <<'PY'\nimport glob\nfrom pathlib import Path\n(Path('..') / '..' / 'platform-services' / 'build' / 'x')"
                    ".write_text('y')\nPY"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.w(cmd), cmd)

    def test_scan_then_write_on_ancestor_stays_blocked(self):
        """훑기 낱말 뒤 쓰기·끝 `/` 낱말 이어 붙임은 그대로 막힌다."""
        cwd = os.path.join(self.top, "svc", "platform-services", "build", "src")
        os.makedirs(cwd)
        for cmd in ("python3 - <<'PY'\nfrom pathlib import Path\nfor p in Path('..').rglob('*.java'):\n    p.write_text('')\nPY",
                    "python3 - <<'PY'\nimport os\nfor r, d, f in os.walk('..'):\n    [os.remove(os.path.join(r, x)) for x in f]\nPY",
                    "python3 -c \"n = 'x'; open('../' + n, 'w')\""):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.w(cmd, cwd), cmd)

    def test_second_argument_dotdot_of_other_calls_stays_blocked(self):
        """동작 I1: `join` 밖 호출의 둘째 인자 `..`은 cwd 기준 쓰기 대상이다."""
        for cmd in ("python3 -c \"import glob, shutil; f = 'a'; shutil.copy(f, '../..')\"",
                    "python3 -c \"import shutil; src = 'a'; shutil.copytree(src, '../..')\"",
                    "python3 -c \"import os, glob; x = 'a'; os.rename(x, '../..')\"",
                    "node -e \"const fs = require('fs'); const s = 'a'; fs.cpSync(s, '../..', {recursive: true})\""):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.w(cmd), cmd)

    def test_mixed_runs_judged_per_run(self):
        """동작 I2: 같은 본문에 `join(HERE, '..', '..')`가 있어도 글자로 시작한 런의 `../..`는 후보다."""
        a = "os.path.join(HERE, '..', '..')"
        b = "shutil.rmtree(os.path.join('..', '..'))"
        for body in (f"{a}; {b}", f"{b}; {a}"):
            with self.subTest(body=body):
                self.assertTrue(self.w(f"python3 -c \"import os, shutil; HERE = 'x'; {body}\""), body)

    def test_tree_writes_on_ancestor_stay_blocked(self):
        for cmd in ("python3 -c \"import shutil; shutil.rmtree('../..')\"",
                    "python3 -c \"import shutil, os; shutil.rmtree(os.path.join('..', '..'))\"",
                    "node -e \"require('fs').rmSync('../..', {recursive: true})\""):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.w(cmd), cmd)


class ContentOnlyLiteralTest(HomeRepoBase):
    """내용으로만 흐르는 글자(따옴표 셋 글자 하나, 고친 글을 `.write(s)`로 쓰는 문자열 고치기 호출의 인자)는
    쓰기 대상이 아니다 — 흘러서 쓰기 대상이 될 수 있는 글자(경로로 쓰는 이름·쓰기 호출 안 고치기·한 인자 replace)는 그대로 막는다."""

    def setUp(self):
        super().setUp()
        self.rules = [f"Edit(/{self.top}/.agents/**)", f"Read(/{self.top}/.agents/**)"]

    def w(self, cmd):
        return g.deny_write_hits(cmd, self.top, self.rules, repo_top=self.top)

    def r(self, cmd):
        return g.deny_read_hits(cmd, self.top, self.rules, repo_top=self.top)

    Q = "'" * 3
    # ⑤ 실측 꼴(세션 기록 fad8538d): 시험 파일 고치기 — 따옴표 셋 속 `".agents/skills/seam/SKILL.md"`와 괄호
    B136 = ("python3 - <<'EOF'\n"
            "p=\"svc/.agents/workflow/session/test_open.py\"; s=open(p,encoding=\"utf-8\").read()\n"
            "s=s.replace(" + Q + "                  \".agents/skills/seam/SKILL.md\", \".agents/rules/git.md\"):" + Q + ","
            + Q + "                  \".agents/skills/seam/SKILL.md\", \".agents/rules/git.md\",\n"
            "                  \".claude/skills/x/a.md\", \".claude/skills/y/a.md\"):" + Q + ")\n"
            "s=s.replace(\"결정 0542\\n\",\"결정 0542 · 더함 → 1361\\n\",1)\n"
            "open(p,\"w\",encoding=\"utf-8\").write(s)\nEOF")

    def test_triple_quoted_fixture_edit_passes(self):
        self.assertEqual(self.w(self.B136), [])
        self.assertEqual(self.r(self.B136), [])

    def test_triple_quoted_inner_code_is_one_literal(self):
        """따옴표 셋 안 괄호·따옴표는 코드 묶음이 아니다 — 짝이 깨져 데이터 자리 셈이 꺼지지 않는다."""
        body = "P = '.agents/x'\nT = " + self.Q + "\n(\n\"c\"" + self.Q + "\nprint(P, T)\n"
        self.assertTrue(g._data_starts(body))
        self.assertNotIn(".agents/x", g._code_path_words(body + "open('o', 'w')\n"))
        # 데이터 범위 안 따옴표 밖 낱말도 뺀다 — 데이터 아닌 따옴표 셋의 낱말은 남는다
        self.assertNotIn(".agents/z", g._code_path_words("T = " + self.Q + "\n.agents/z\n" + self.Q + "\nprint(T)\nopen('o', 'w')\n"))
        self.assertIn(".agents/z", g._code_path_words("exec(" + self.Q + "\n.agents/z\n" + self.Q + ")\nopen('o', 'w')\n"))
        # 지정 머리는 `;` 뒤도 — 따옴표 글자 안 `; x = …`는 지정이 아니다
        self.assertIn(".agents/w", g._code_path_words("print('a; p = 1')\np = '.agents/w'\nopen(p, 'w')\n"))

    def test_replace_content_written_passes(self):
        for body in ("p = 'x.py'\ns = open(p).read()\ns = s.replace('a', '.agents/skills/seam/SKILL.md')\nopen(p, 'w').write(s)",
                     "import re\np = 'x.py'\ns = open(p).read()\ns = re.sub(r'a', '.agents/y', s)\nopen(p, 'w').write(s)",
                     "from pathlib import Path\np = Path('x.py')\np.write_text(p.read_text().replace('a', '.agents/y'))",
                     "p = 'x.py'\ns = open(p).read().replace('a', '.agents/y', 1)\nwith open(p, 'w') as f:\n    f.write(s)"):
            cmd = f"python3 - <<'EOF'\n{body}\nEOF"
            with self.subTest(body=body):
                self.assertEqual(self.w(cmd), [], body)

    def test_real_targets_stay_blocked(self):
        for body in ("p = 'x'.replace('x', '.agents/y')\nopen(p, 'w').write('z')",
                     "s = 'x'\nopen(s.replace('x', '.agents/y'), 'w')",
                     "s = 'x'\ns = s.replace('x', '.agents/y')\nopen(s, 'w')",
                     "s = 'x'\ns = s.replace('x', \"open('.agents/y', 'w')\")\nexec(s)",
                     "import shutil\nf = 'a'\nshutil.copy(f, '.agents/y')",
                     "import os\nos.replace('a', '.agents/y')\nprint('x')",
                     "from pathlib import Path\nx = Path('a').replace('.agents/y')\nprint(x)",
                     "exec(" + self.Q + "open('.agents/y', 'w')" + self.Q + ")",
                     "T = " + self.Q + "\n" + self.Q + "\nopen('.agents/y', 'w')",
                     # 동작 Critical: 한 줄 글자 안 `'''`는 따옴표 셋 머리가 아니다
                     "print(\"" + self.Q + "\")\nopen('.agents/y', 'w').write('z')\nprint(\"" + self.Q + "\")",
                     "print('a')  # " + self.Q + "\nopen('.agents/y', 'w').write('z')\nprint('b')  # " + self.Q,
                     # 동작 Important: 이름 바꾼 os의 두 인자 replace는 고치기가 아니다
                     "print(__import__('os').replace('a', '.agents/y'))"):
            cmd = f"python3 - <<'EOF'\n{body}\nEOF"
            with self.subTest(body=body):
                self.assertTrue(self.w(cmd), body)
        # 이름 바꾼 os(쓰기 의도 낱말 없음 — 옛 판도 쓰기는 못 봄)는 읽기 판정이 그대로 막는다
        for body in ("print(__import__('os').replace('a', '.agents/y'))",
                     "import os as o\nprint(o.replace('a', '.agents/y'))",
                     "import os as o\nx = o.replace('a', '.agents/y')\nprint(x)",
                     "from os import path\nimport os\nf = os\nprint(f.replace('a', '.agents/y'))",
                     "import os\nf = os\nprint(f.replace('a', '.agents/y'))"):
            cmd = f"python3 - <<'EOF'\n{body}\nEOF"
            with self.subTest(body=body):
                self.assertTrue(self.r(cmd), body)

    def test_non_data_triple_stays_blocked(self):
        """데이터 아닌 따옴표 셋 속 글자는 읽기·git 판정에서도 그대로 후보다."""
        read = "python3 - <<'EOF'\nexec(" + self.Q + "\nprint(open(\".agents/y\").read())\n" + self.Q + ")\nEOF"
        self.assertTrue(self.r(read), read)
        git = "python3 - <<'EOF'\nimport os\nexec(" + self.Q + "\nos.system(\"git push origin x\")\n" + self.Q + ")\nEOF"
        self.assertTrue(g.reason(git, os.path.join(self.t, "lead"), self.top), git)
        # 동작 Critical: 한 줄 글자 안 `'''` 둘 사이의 읽기·git
        mark = "print(\"" + self.Q + "\")"
        read = f"python3 - <<'EOF'\n{mark}\nprint(open('.agents/y').read())\n{mark}\nEOF"
        self.assertTrue(self.r(read), read)
        git = f"python3 - <<'EOF'\nimport os\n{mark}\nos.system(\"git push origin x\")\n{mark}\nEOF"
        self.assertTrue(g.reason(git, os.path.join(self.t, "lead"), self.top), git)

    def test_assign_head_after_semicolon(self):
        """동작 Minor: `;` 뒤 지정 머리(`p = …; s = open(p).read`)도 데이터 상수 셈에 든다."""
        body = "p = 'x.py'; s = open(p).read()\ns = s.replace('a', '.agents/y')\nopen(p, 'w').write(s)"
        self.assertEqual(self.w(f"python3 - <<'EOF'\n{body}\nEOF"), [], body)

    def test_inner_call_args_stay_blocked(self):
        """고치기 호출 안쪽의 다른 호출 인자는 데이터가 아니다."""
        for body in ("p = 'x.py'\ns = open(p).read()\ns = s.replace('a', open('.agents/y').read())\nopen(p, 'w').write(s)",
                     "from pathlib import Path\np = 'x.py'\ns = open(p).read()\n"
                     "s = s.replace('a', Path('.agents/y').read_text())\nopen(p, 'w').write(s)"):
            cmd = f"python3 - <<'EOF'\n{body}\nEOF"
            with self.subTest(body=body):
                self.assertTrue(self.r(cmd), body)
                self.assertTrue(self.w(cmd), body)


class GateTest(unittest.TestCase):
    """켜는 깃발(`gate_reason`) — 셸 git 그 하위 명령(`block_git`)과 그 하위 명령의 인자(`block_git_arg`, `<하위>:<인자>`).
    깃발이 있을 때만 막고, `-C`·`sh -c`·`eval`·`$( )`·백틱·셸 본문·find -exec·실행기 꼬리 안까지 본다. 셸 `-n`(문법 검사만)의 본문은 보지 않는다."""

    ARGS = ("commit:--amend", "reset:--soft", "push:-f")

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        with open(os.path.join(self.tmp, "x.sh"), "w") as f:
            f.write("cd sub\ngit merge x\n")
        with open(os.path.join(self.tmp, "ok.sh"), "w") as f:
            f.write("git status\nls merge\n")

    def gate(self, cmd):
        return g.gate_reason(cmd, self.tmp, block_git=("merge", "pull", "rebase", "am"))

    def arg_gate(self, cmd):
        return g.gate_reason(cmd, self.tmp, block_git_arg=self.ARGS)

    def test_blocked_with_flags(self):
        for cmd in ("git merge dev/main", "git -C /w merge x", "sh -c 'git pull'", "eval git merge x", "git rebase main", "git am x.patch",
                    "echo `git merge x`", "echo $(git pull)", f"zsh {self.tmp}/x.sh", "bash <<'E'\ngit merge x\nE",
                    "caffeinate -i git merge x", "nohup git rebase main"):
            self.assertTrue(self.gate(cmd), cmd)

    def test_passes(self):
        for cmd in ("git merge-base a b", "git log --merges", "git status", f"zsh {self.tmp}/ok.sh",
                    "cat > n.md <<'E'\n`git merge x`\nE", "grep -n merge README.md", "echo git merge x"):
            self.assertIsNone(self.gate(cmd), cmd)

    def test_off_without_flags(self):
        for cmd in ("git merge dev/main", "git commit --amend"):
            self.assertIsNone(g.gate_reason(cmd, self.tmp), cmd)

    def test_messages_are_neutral(self):
        msg = self.gate("git merge x")
        self.assertIn("git merge", msg)
        self.assertIn("[막힘]", msg)
        self.assertIn("리드", msg)
        arg_msg = self.arg_gate("git commit --amend")
        self.assertIn("commit --amend", arg_msg)

    def test_block_git_arg(self):
        for cmd in ("git commit --amend", "git commit -m x --amend", "git commit --amen", "git commit --amend=x",
                    "git -C /w commit --amend", "git -c a=b commit --amend", "sh -c 'git commit --amend'", "eval git reset --soft HEAD~1",
                    "git reset --soft HEAD~1", "echo $(git commit --amend)", "git push -f", "git push -fu origin x",
                    "bash <<'E'\ngit commit --amend\nE",
                    "git commit --am", "git commit --a", "git reset --so HEAD",  # 줄임 — 모호하면 git이 오류
                    "git commit -m --amend"):  # 옵션 값 자리는 가르지 않는다 — 막는 쪽
            self.assertTrue(self.arg_gate(cmd), cmd)

    def test_block_git_arg_passes(self):
        for cmd in ("git commit -m x", "git reset --mixed HEAD", "git reset HEAD -- a",
                    "git commit -- --amend", "git log --amend-like", "git push origin x", "git push --follow-tags",
                    "git status", "echo commit --amend"):
            self.assertIsNone(self.arg_gate(cmd), cmd)

    def test_block_git_arg_with_block_git(self):
        both = dict(block_git=("merge",), block_git_arg=("commit:--amend",))
        self.assertTrue(g.gate_reason("git merge x", self.tmp, **both))
        self.assertTrue(g.gate_reason("git commit --amend", self.tmp, **both))
        self.assertIsNone(g.gate_reason("git commit -m x", self.tmp, **both))
        self.assertIsNone(g.gate_reason("git commit --amend", self.tmp, block_git=("merge",)))

    def test_find_exec(self):
        for cmd in ("find . -exec true \\; -exec git commit --amend \\;", "find . -exec git commit --amend \\;"):
            self.assertTrue(self.arg_gate(cmd), cmd)
        self.assertTrue(self.gate("find . -exec true \\; -exec git merge x \\;"))
        self.assertTrue(self.gate("find . \\( -exec true \\; \\) -exec git merge x \\;"))
        self.assertTrue(self.gate("find . -exec sh -c 'git pull' \\;"))
        self.assertIsNone(self.gate("find . -name '*.sh' -exec chmod +x {} \\;"))

    def test_runner_tails(self):
        self.assertTrue(self.arg_gate("caffeinate -i git commit --amend"))
        self.assertTrue(self.gate("script -q git merge x"))  # 옵션 뒤 첫 낱말이 돌릴 명령

    def test_shell_noexec_passes(self):
        for cmd in (f"bash -o noexec {self.tmp}/x.sh", f"bash -n {self.tmp}/x.sh", f"sh -n {self.tmp}/x.sh", f"bash -nx {self.tmp}/x.sh",
                    "bash -n -c 'git merge a'", "bash -n <<'E'\ngit merge a\nE"):
            self.assertIsNone(self.gate(cmd), cmd)
        for cmd in (f"bash {self.tmp}/x.sh", f"bash -x {self.tmp}/x.sh", "bash -c 'git merge a'", "bash -in -c 'git merge a'",
                    f"bash -n -i {self.tmp}/x.sh", "bash -n +n -c 'git merge a'", f"bash -n +o noexec {self.tmp}/x.sh"):
            self.assertTrue(self.gate(cmd), cmd)


if __name__ == "__main__":
    unittest.main()
