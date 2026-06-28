# SSPlayer script statements (Creator-Defined Statements) — casual演出 verbs.
#
# Adds a one-shot effect verb you can write directly in the script (no `$`):
#
#     ss effect "ss_assets/ParticleEffect/e038.ssab" at Transform(xpos=640, ypos=360)
#     ss effect "ss_assets/ParticleEffect/e040b.ssab" at truecenter wait
#
# Grammar:  ss effect <ssab-path-expr> [at <expr>] [wait]
#   - <expr> after `at` is any Transform / ATL / position (evaluated at runtime)
#   - `wait` blocks for one playthrough, then hides (a cutscene beat)
#
# Thin sugar over ss_show_effect() (see ss_helpers.rpy). Registered in
# `python early` so it is available when scripts parse; the registration is
# guarded, and the parse/execute only run when a script actually uses `ss effect`,
# so this file is inert until you opt in. Drop it to remove the statement.

python early:

    def _ss_effect_parse(lex):
        path = lex.simple_expression()
        at = None
        if lex.keyword("at"):
            at = lex.simple_expression()
        wait = bool(lex.keyword("wait"))
        lex.expect_eol()
        return (path, at, wait)

    def _ss_effect_execute(parsed):
        path, at, wait = parsed
        if not path:
            return
        target = renpy.python.py_eval(path)
        at_value = renpy.python.py_eval(at) if at else None
        ss_show_effect(target, at=at_value, wait=wait)

    def _ss_effect_lint(parsed):
        if not parsed or not parsed[0]:
            renpy.error("ss effect: expected a .ssab path expression.")

    try:
        renpy.register_statement(
            "ss effect",
            parse=_ss_effect_parse,
            execute=_ss_effect_execute,
            lint=_ss_effect_lint,
        )
    except Exception:
        pass
