"""Regression: all UI signal handlers must exist on their widget class.

This AST-based check runs even on hosts without the PyQt6 runtime. It catches
Discover's former nonexistent update_mark_label callback before distribution.
"""
import ast
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "main.py"


class GuiStartupWiringTests(unittest.TestCase):
    def test_ui_init_signal_callbacks_exist(self):
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

        def methods_for(name, seen=None):
            seen = set() if seen is None else seen
            if name in seen or name not in classes:
                return set()
            seen.add(name)
            obj = classes[name]
            names = {n.name for n in obj.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for base in obj.bases:
                if isinstance(base, ast.Name):
                    names.update(methods_for(base.id, seen))
            return names

        examined = 0
        for class_name, node in classes.items():
            # QObject/QWidget/QDialog inherited API methods need not appear in main.py.
            allowed = methods_for(class_name) | {"reject", "accept", "close"}
            for method in node.body:
                if not isinstance(method, ast.FunctionDef) or method.name != "__init__":
                    continue
                for expr in ast.walk(method):
                    if not isinstance(expr, ast.Call):
                        continue
                    fn = expr.func
                    if not isinstance(fn, ast.Attribute) or fn.attr != "connect":
                        continue
                    for arg in expr.args:
                        # Covers direct QObject signal connections like:
                        # self.table.itemSelectionChanged.connect(self.callback)
                        if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id == "self":
                            examined += 1
                            self.assertIn(arg.attr, allowed,
                                          f"{class_name}.__init__ connects undefined self.{arg.attr}")
        self.assertGreaterEqual(examined, 20)

    def test_discover_wiring_uses_existing_handler(self):
        src = MAIN.read_text(encoding="utf-8")
        start = src.index("class DiscoverPanel(")
        end = src.index("class PackageDropTable(", start)
        panel = src[start:end]
        self.assertIn("self.table.itemSelectionChanged.connect(self.update_open_button)", panel)
        self.assertNotIn("update_mark_label", panel)
        self.assertIn("self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)", panel)

    def test_center_keeps_ten_tabs(self):
        src = MAIN.read_text(encoding="utf-8")
        start = src.index("class Center(")
        panel = src[start:]
        self.assertIn("('Flatpak', 'AppImage', 'RPM', 'DEB', 'Arch', 'Snap')", panel)
        for name in ("UpdatesPanel", "DiscoverPanel", "BackupPanel", "InfoPanel"):
            self.assertIn(f"{name}(", panel)


if __name__ == "__main__":
    unittest.main()
