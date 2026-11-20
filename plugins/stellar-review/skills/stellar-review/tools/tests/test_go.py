"""Tests for Go support: unit extraction (raw strings, type forms,
receiver-qualified methods), boundary sites, import edges, and test-file
handling."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import briefs  # noqa: E402
import facts  # noqa: E402
import ledger  # noqa: E402
from helpers import RepoFixture  # noqa: E402
from units import extract_units, strip_strings_comments  # noqa: E402

RAW_STRING_TEST = '''\
package instance

func TestDryRun(t *testing.T) {
	body := `{
  "data": {
    "id": "abc"
  }
}`
	assert.Equal(t, body, out)
	assert.Equal(t, 1, calls)
}

func TestNext(t *testing.T) {
}
'''


def go_units(content, path="pkg/x.go"):
    return {u["name"]: u for u in extract_units(path, content)}


class TestBraceScanner(unittest.TestCase):
    def test_multiline_raw_string_braces_do_not_end_the_unit(self):
        u = go_units(RAW_STRING_TEST)
        self.assertEqual((u["TestDryRun"]["start"], u["TestDryRun"]["end"]), (3, 11))
        self.assertIn("assert.Equal(t, 1, calls)", u["TestDryRun"]["body"])
        self.assertEqual(u["TestNext"]["start"], 13)

    def test_raw_string_state_threads_across_lines(self):
        _, state = strip_strings_comments("x := `{", "go", "")
        self.assertEqual(state, "`")
        cleaned, state = strip_strings_comments('}` + "}"', "go", state)
        self.assertEqual((cleaned.strip(), state), ("+", ""))

    def test_braces_in_comments_runes_and_escaped_quotes_are_ignored(self):
        src = (
            "func f() {\n"
            "\t/* { open\n"
            "\t   still comment { */\n"
            "\tr := '{'\n"
            "\tq := '}'\n"
            "\ts := \"say \\\"{\\\" now\"\n"
            "\t// } in a line comment\n"
            "}\n"
            "\n"
            "func g() {\n}\n"
        )
        u = go_units(src)
        self.assertEqual((u["f"]["start"], u["f"]["end"]), (1, 8))
        self.assertEqual(u["g"]["start"], 10)

    def test_raw_string_state_is_go_only(self):
        for lang in ("rust", "javascript", "typescript"):
            _, state = strip_strings_comments("let x = `{", lang, "")
            self.assertEqual(state, "", lang)


def spans(path, content):
    return {u["name"]: (u["start"], u["end"]) for u in extract_units(path, content)}


class TestJsTsKeepPreChangeBehaviour(unittest.TestCase):
    """Raw-string state is Go only, so JS and TS scan exactly as before
    Go support landed."""

    TEMPLATE = ("function a() {\n  const s = `{\n  \"k\": 1\n}`;\n  return s;\n}\n"
                "function b() {\n  return 1;\n}\n")
    NESTED = ("function a() {\n  const s = `x ${ `y` } z`;\n  return s;\n}\n"
              "function b() {\n  return 1;\n}\n")
    REGEX = ("function a() {\n  const re = /`/;\n  return re;\n}\n"
             "function b() {\n  return 1;\n}\nfunction c() {\n  return 2;\n}\n")

    def test_multiline_template_literal_with_braces_still_ends_the_unit_early(self):
        # Known limitation, unchanged from before Go support: the stray `}`
        # on the template's last line closes `a` at line 4 (it really ends
        # at line 6). Not fixed here: this change is Go only.
        for ext in ("js", "ts"):
            self.assertEqual(spans("x." + ext, self.TEMPLATE),
                             {"a": (1, 4), "b": (7, 9)}, ext)

    def test_nested_template_literal_units_are_unaffected(self):
        for ext in ("js", "ts"):
            self.assertEqual(spans("x." + ext, self.NESTED),
                             {"a": (1, 4), "b": (5, 7)}, ext)

    def test_lone_backtick_in_a_regex_literal_does_not_swallow_following_units(self):
        for ext in ("js", "ts"):
            self.assertEqual(spans("x." + ext, self.REGEX),
                             {"a": (1, 4), "b": (5, 7), "c": (8, 10)}, ext)


class TestTypeUnits(unittest.TestCase):
    SRC = '''\
package p

type Config struct {
	Name string
}

type Handler func(ctx context.Context) error

type Level int

type Alias = Config

type Set[T comparable] map[T]struct{}

type Reader interface {
	Read() error
}

type (
	ID    string
	Pair  struct {
		A, B int
	}
	// Doc comment
	Fn func(int) int
)

func after() {}
'''

    def test_non_struct_types_are_units(self):
        u = go_units(self.SRC)
        for name in ("Config", "Handler", "Level", "Alias", "Set", "Reader"):
            self.assertEqual(u[name]["kind"], "type", name)
        # single-line declarations end on their own line
        self.assertEqual((u["Handler"]["start"], u["Handler"]["end"]), (7, 7))
        self.assertEqual((u["Level"]["start"], u["Level"]["end"]), (9, 9))
        self.assertEqual((u["Alias"]["start"], u["Alias"]["end"]), (11, 11))
        self.assertEqual((u["Config"]["start"], u["Config"]["end"]), (3, 5))

    def test_grouped_type_block_yields_one_unit_per_spec(self):
        u = go_units(self.SRC)
        self.assertEqual((u["ID"]["start"], u["ID"]["end"]), (20, 20))
        self.assertEqual((u["Pair"]["start"], u["Pair"]["end"]), (21, 23))
        self.assertEqual(u["Fn"]["start"], 25)
        # struct fields inside a spec are not specs; the block ends at `)`
        self.assertNotIn("A", u)
        self.assertNotIn("type", u)
        self.assertEqual(u["after"]["start"], 28)

    def test_multiline_func_type_in_a_group_does_not_end_the_group_or_make_units(self):
        src = ("type (\n\tHandler func(\n\t\tctx int,\n\t) error\n\n"
               "\tNext struct {\n\t\tA int\n\t}\n\tLast string\n)\n\nfunc After() {\n}\n")
        u = spans("x.go", src)
        self.assertEqual(u, {"Handler": (2, 4), "Next": (6, 8), "Last": (9, 9), "After": (12, 13)})
        self.assertNotIn("ctx", u)

    def test_type_keyword_inside_a_function_is_not_a_unit(self):
        u = go_units("func f() {\n\ttype local int\n}\n")
        self.assertEqual(set(u), {"f"})


class TestReceivers(unittest.TestCase):
    SRC = '''\
package p

func (c *Cache[K, V]) Get(k K) V {
	return c.m[k]
}

func (a Alpha) Run() {}

func (b *Beta) Run() {}

func (_ Alpha) String() string { return "a" }

func Run() {}
'''

    def test_methods_are_qualified_by_receiver_type(self):
        u = go_units(self.SRC)
        self.assertEqual(set(u), {"Cache.Get", "Alpha.Run", "Beta.Run", "Alpha.String", "Run"})

    def test_same_named_methods_on_different_types_keep_distinct_ids(self):
        ids = {u["id"] for u in extract_units("pkg/x.go", self.SRC)}
        self.assertIn("pkg/x.go::Alpha.Run", ids)
        self.assertIn("pkg/x.go::Beta.Run", ids)
        self.assertIn("pkg/x.go::Run", ids)

    def test_bodyless_func_declaration_ends_on_its_line(self):
        u = go_units("func Sum(a, b int) int\n\nfunc other() {\n}\n")
        self.assertEqual(u["Sum"]["end"], 1)

    def test_multiline_signature_is_one_unit(self):
        u = go_units("func (s *S) Do(\n\ta int,\n) error {\n\treturn nil\n}\n")
        self.assertEqual((u["S.Do"]["start"], u["S.Do"]["end"]), (1, 5))

    def test_signature_identifiers_include_the_bare_method_name(self):
        u = go_units(self.SRC)["Alpha.Run"]
        self.assertIn("Run", facts.signature_identifiers(u))
        self.assertIn("Alpha.Run", facts.signature_identifiers(u))


def go_sites(*code_lines):
    content = "\n".join(code_lines) + "\n"
    added = set(range(1, len(code_lines) + 1))
    return [s["kind"] for s in facts.extract_sites("x.go", content, added, [])]


class TestGoSites(unittest.TestCase):
    def test_ignored_error(self):
        self.assertIn("ignored_error", go_sites("\t_ = f.Close()"))
        self.assertIn("ignored_error", go_sites("\tv, _ := cmd.Flags().GetBool(\"x\")"))
        self.assertIn("ignored_error", go_sites("\tif dry, _ := cmd.Flags().GetBool(\"d\"); dry {"))
        self.assertIn("ignored_error", go_sites("\t_, _ = fmt.Fprintln(w, x)"))
        self.assertNotIn("ignored_error", go_sites("\t_ = x"))
        self.assertNotIn("ignored_error", go_sites("\tfor _, v := range xs {"))
        self.assertNotIn("ignored_error", go_sites("\tv, ok := m[k]"))
        self.assertNotIn("ignored_error", go_sites("\t// _ = f()"))

    def test_any(self):
        for line in ("func f(x any) {", "var m map[string]any", "xs := []any{1}",
                     "func F[T any](t T) {}", "var v interface{}"):
            self.assertIn("go_any", go_sites(line), line)
        for line in ("// accepts any value", 'msg := "any, really"', "n := anyway(x)",
                     "y := any(x)"):
            self.assertNotIn("go_any", go_sites(line), line)

    def test_unchecked_type_assertion(self):
        self.assertIn("unchecked_assert", go_sites("\ts := v.(string)"))
        self.assertIn("unchecked_assert", go_sites("\tp := v.(*Config)"))
        self.assertNotIn("unchecked_assert", go_sites("\ts, ok := v.(string)"))
        self.assertNotIn("unchecked_assert", go_sites("\tif s, ok = v.(string); ok {"))
        self.assertNotIn("unchecked_assert", go_sites("\tswitch t := v.(type) {"))
        self.assertNotIn("unchecked_assert", go_sites("\tfmt.Println(x)"))

    def test_panic(self):
        self.assertIn("panic", go_sites('\tpanic("boom")'))
        self.assertNotIn("panic", go_sites("\t// do not panic(x)"))
        self.assertNotIn("panic", go_sites("\tpanicked := true"))

    def test_mutex_and_lock(self):
        self.assertIn("go_lock", go_sites("\tmu sync.Mutex"))
        self.assertIn("go_lock", go_sites("\tmu sync.RWMutex"))
        self.assertIn("go_lock", go_sites("\ts.mu.Lock()"))
        self.assertIn("go_lock", go_sites("\ts.mu.RLock()"))
        self.assertNotIn("go_lock", go_sites("\ts.mu.Unlock()"))
        self.assertNotIn("go_lock", go_sites("\tvar wg sync.WaitGroup"))

    def test_goroutine_start(self):
        self.assertIn("goroutine", go_sites("\tgo func() {"))
        self.assertIn("goroutine", go_sites("\tgo worker(ch)"))
        self.assertIn("goroutine", go_sites("\tgo s.serve(ctx)"))
        self.assertNotIn("goroutine", go_sites("\tgoto done"))
        self.assertNotIn("goroutine", go_sites("\tgoroutines := 3"))

    def test_go_kinds_do_not_fire_on_other_languages(self):
        kinds = [s["kind"] for s in facts.extract_sites(
            "x.rs", "panic(x);\n_ = f();\n", {1, 2}, [])]
        self.assertNotIn("panic", kinds)
        self.assertNotIn("ignored_error", kinds)

    def test_boundaries_pass_owns_the_go_kinds(self):
        for kind in ("ignored_error", "go_any", "unchecked_assert", "panic",
                     "go_lock", "goroutine"):
            self.assertIn(kind, briefs.SITE_OWNERS["boundaries"])


GO_MOD = "module example.com/app\n\ngo 1.22\n"


class TestGoImports(RepoFixture):
    def build(self, importer):
        self.write("go.mod", GO_MOD)
        self.write("internal/store/store.go", "package store\n\nfunc Get() {}\n")
        self.write("cmd/main.go", importer)
        base = self.commit("base")
        self.write("internal/store/store.go", "package store\n\nfunc Get(id string) {}\n")
        head = self.commit("change")
        return facts.build_facts(self.dir, base, head)

    def test_single_line_and_grouped_imports_resolve_to_package_dirs(self):
        f = self.build(
            'package main\n\nimport "example.com/app/internal/store"\n\nfunc main() {}\n')
        self.assertEqual(f["deps"]["cmd/main.go"], ["internal/store"])
        g = self.build(
            'package main\n\nimport (\n\t"fmt"\n\tdb "example.com/app/internal/store"\n'
            '\t_ "github.com/lib/pq"\n)\n\nfunc main() {}\n')
        self.assertEqual(g["deps"]["cmd/main.go"], ["internal/store"])

    def test_stdlib_and_third_party_imports_are_not_edges(self):
        f = self.build('package main\n\nimport (\n\t"fmt"\n\t"github.com/spf13/cobra"\n)\n')
        self.assertNotIn("cmd/main.go", f["deps"])

    def test_no_go_mod_means_no_go_edges(self):
        self.write("a/a.go", 'package a\n\nimport "example.com/app/b"\n')
        base = self.commit("base")
        self.write("a/a.go", 'package a\n\nimport "example.com/app/b"\n\nfunc F() {}\n')
        head = self.commit("change")
        self.assertEqual(facts.build_facts(self.dir, base, head)["deps"], {})

    def test_signature_change_dirties_importing_files(self):
        f = self.build(
            'package main\n\nimport "example.com/app/internal/store"\n\nfunc main() {}\n')
        sig_unit = [u for u in f["units"] if u["id"] == "internal/store/store.go::Get"][0]
        self.assertTrue(sig_unit["signature_changed"])
        dirty = ledger.dependency_dirty_files(f, {"units": {}})
        self.assertEqual(dirty, {"cmd/main.go"})

    def test_test_files_are_not_importable_modules(self):
        self.assertEqual(ledger.module_of("internal/store/store.go"), "internal/store")
        self.assertIsNone(ledger.module_of("internal/store/store_test.go"))


class TestGoTestFiles(RepoFixture):
    def test_test_files_are_flagged_and_never_size_gated(self):
        body = "".join(f"\tx{i} := {i}\n" for i in range(1100))
        self.write("a/small.go", "package a\n")
        self.write("a/small_test.go", "package a\n")
        base = self.commit("base")
        for path in ("a/small.go", "a/small_test.go"):
            self.write(path, "package a\n\nfunc F() {\n" + body + "}\n")
        head = self.commit("grow")
        f = facts.build_facts(self.dir, base, head)
        rec = {x["path"]: x for x in f["files"]}
        self.assertTrue(rec["a/small_test.go"]["is_test"])
        self.assertFalse(rec["a/small.go"]["is_test"])
        self.assertTrue(rec["a/small.go"]["crossed_1k"])
        self.assertFalse(rec["a/small_test.go"]["crossed_1k"])
        # test units are still extracted and reviewed, flagged as tests
        unit = [u for u in f["units"] if u["path"] == "a/small_test.go"][0]
        self.assertTrue(unit["is_test"])
        self.assertTrue(unit["changed"])
        self.assertIn("test", ", ".join(briefs.unit_block(unit)[:1]))

    def test_non_go_files_are_not_tests(self):
        self.write("a/x_test.rs", "fn a() {}\n")
        base = self.commit("base")
        self.write("a/x_test.rs", "fn a() {}\nfn b() {}\n")
        head = self.commit("c")
        f = facts.build_facts(self.dir, base, head)
        self.assertFalse(f["files"][0]["is_test"])


if __name__ == "__main__":
    unittest.main()
