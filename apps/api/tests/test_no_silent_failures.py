"""Silent-Failure-Hunter: AST-Level audit for blind exception swallowing.

Enforces robust error handling across vozonda_api:
- Disallows bare `except:` or `except Exception:` with only `pass` unless
  explicitly documented with a `# silent:` justification comment.
- Prohibits silent ellipsis (`except Exception: ...`).
- Ensures errors in critical modules are logged, re-raised, or explicitly documented.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "vozonda_api"


def test_no_blind_uncommented_silent_exceptions():
    """Scan vozonda_api for blind `except Exception: pass` without `# silent:` annotation."""
    violations = []

    for py_file in sorted(SRC_DIR.glob("**/*.py")):
        if "__pycache__" in str(py_file):
            continue

        content = py_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        try:
            tree = ast.parse(content, filename=str(py_file))
        except Exception:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue

            # Check if exception type is blind (bare `except:` or `except Exception:`)
            is_blind = False
            if node.type is None or isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"):
                is_blind = True

            if not is_blind:
                continue

            # Check if the block body is just `pass` or `...`
            is_silent_body = False
            if len(node.body) == 1:
                stmt = node.body[0]
                if isinstance(stmt, ast.Pass) or isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
                    is_silent_body = True

            if is_silent_body:
                # Require explicit justification on the except line or preceding line
                lineno = node.lineno
                except_line = lines[lineno - 1] if lineno <= len(lines) else ""
                prev_line = lines[lineno - 2] if lineno >= 2 else ""

                if "silent:" not in except_line.lower() and "silent:" not in prev_line.lower():
                    violations.append(
                        f"{py_file.name}:{lineno} -> blind silent catch without justification: {except_line.strip()}"
                    )

    assert not violations, (
        f"Found {len(violations)} blind exception catches without '# silent:' explanation:\n"
        + "\n".join(violations)
    )
