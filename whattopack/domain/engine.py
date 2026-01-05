
from __future__ import annotations
import ast
import math
from typing import Any, Dict, List, Tuple
from ..models import Trip
from .util import days_between

class SafeExprEvaluator:
    """Safe arithmetic/boolean evaluator for rules quantity.calc."""
    ALLOWED_FUNCS = {"ceil": math.ceil, "floor": math.floor, "round": round, "min": min, "max": max}
    ALLOWED_NAMES = {"days", "cycle", "avg_temp_c", "precip_mm", "snowfall_mm", "temp_profile"}

    def eval(self, expression: str, context: dict) -> int:
        node = ast.parse(str(expression), mode="eval")
        value = self._eval_node(node.body, context)
        return max(1, int(math.ceil(float(value))))

    def _eval_node(self, node, ctx):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.ALLOWED_NAMES: raise ValueError(f"Unknown name '{node.id}'")
            return ctx.get(node.id, 0)
        if isinstance(node, ast.BinOp):
            l = self._eval_node(node.left, ctx); r = self._eval_node(node.right, ctx)
            if isinstance(node.op, ast.Add): return l + r
            if isinstance(node.op, ast.Sub): return l - r
            if isinstance(node.op, ast.Mult): return l * r
            if isinstance(node.op, ast.Div): return l / r
            if isinstance(node.op, ast.FloorDiv): return l // r
            if isinstance(node.op, ast.Mod): return l % r
            raise ValueError("Operator not allowed")
        if isinstance(node, ast.UnaryOp):
            o = self._eval_node(node.operand, ctx)
            if isinstance(node.op, ast.UAdd): return +o
            if isinstance(node.op, ast.USub): return -o
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn not in self.ALLOWED_FUNCS: raise ValueError(f"Function '{fn}' not allowed")
            args = [self._eval_node(a, ctx) for a in node.args]
            return self.ALLOWED_FUNCS[fn](*args)
        if isinstance(node, ast.IfExp):
            cond = self._eval_bool(node.test, ctx)
            return self._eval_node(node.body if cond else node.orelse, ctx)
        if isinstance(node, ast.Compare):
            return 1 if self._eval_bool(node, ctx) else 0
        raise ValueError("Unsupported expression")

    def _eval_bool(self, node, ctx) -> bool:
        if isinstance(node, ast.Name):
            return bool(ctx.get(node.id, None))
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Compare):
            left_val = self._eval_node(node.left, ctx); result = True
            for op, comparator in zip(node.ops, node.comparators):
                right_val = self._eval_comparator_value(comparator, ctx)
                if   isinstance(op, ast.Eq):    ok = (left_val == right_val)
                elif isinstance(op, ast.NotEq): ok = (left_val != right_val)
                elif isinstance(op, ast.Lt):    ok = (left_val <  right_val)
                elif isinstance(op, ast.LtE):   ok = (left_val <= right_val)
                elif isinstance(op, ast.Gt):    ok = (left_val >  right_val)
                elif isinstance(op, ast.GtE):   ok = (left_val >= right_val)
                elif isinstance(op, ast.In):    ok = self._in_membership(left_val, right_val)
                elif isinstance(op, ast.NotIn): ok = not self._in_membership(left_val, right_val)
                else: raise ValueError("Comparison operator not allowed")
                if not ok: result = False; break
                left_val = right_val
            return result
        raise ValueError("Unsupported boolean expression")

    def _eval_comparator_value(self, node, ctx):
        if isinstance(node, ast.Constant): return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.ALLOWED_NAMES: raise ValueError(f"Unknown name '{node.id}'")
            return ctx.get(node.id, None)
        if isinstance(node, (ast.List, ast.Tuple)):
            vals = []
            for elt in node.elts:
                if not isinstance(elt, ast.Constant): raise ValueError("Only constant lists/tuples allowed")
                vals.append(elt.value)
            return tuple(vals)
        if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Call, ast.IfExp, ast.Compare)):
            return self._eval_node(node, ctx)
        raise ValueError("Unsupported comparator value")

    @staticmethod
    def _in_membership(left, right) -> bool:
        return isinstance(right, (list, tuple)) and (left in right)


def cond_pass(cond: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    if not cond: return False
    if cond.get("always"): return True
    if "carry_on_only" in cond and bool(cond["carry_on_only"]) != bool(ctx["carry_on_only"]): return False
    if "season_in" in cond and ctx["season"] not in cond["season_in"]: return False
    if "temp_in"   in cond and ctx["temp_profile"] not in cond["temp_in"]: return False
    if "activity_in" in cond:
        have, want = set(ctx["activities"]), set(cond["activity_in"])
        if have.isdisjoint(want): return False
    if "days_ge" in cond and not (ctx["days"] >= cond["days_ge"]): return False
    if "days_le" in cond and not (ctx["days"] <= cond["days_le"]): return False
    if "cycle_ge" in cond and not (ctx["cycle"] >= cond["cycle_ge"]): return False
    if "cycle_le" in cond and not (ctx["cycle"] <= cond["cycle_le"]): return False
    if "avg_temp_c_lt" in cond and ctx["avg_temp_c"] is not None and not (ctx["avg_temp_c"] < cond["avg_temp_c_lt"]): return False
    if "avg_temp_c_ge" in cond and ctx["avg_temp_c"] is not None and not (ctx["avg_temp_c"] >= cond["avg_temp_c_ge"]): return False
    if "precip_mm_gt"  in cond and ctx["precip_mm"]  is not None and not (ctx["precip_mm"]  > cond["precip_mm_gt"]): return False
    if "snowfall_mm_gt"in cond and ctx["snowfall_mm"]is not None and not (ctx["snowfall_mm"]> cond["snowfall_mm_gt"]): return False
    def eval_block(b): return cond_pass(b, ctx)
    if "all" in cond and not all(eval_block(b) for b in cond["all"]): return False
    if "any" in cond and  cond["any"] and not any(eval_block(b) for b in cond["any"]): return False
    if "not" in cond and eval_block(cond["not"]): return False
    return True


class RuleEngine:
    def __init__(self, rules: dict):
        self.rules = rules
        self.evalr = SafeExprEvaluator()

    def compute(self, trip: Trip) -> List[Tuple[str, str, int]]:
        days = days_between(trip.start_date, trip.end_date)
        cycle = min(days, max(1, trip.laundry_every_n_days))
        ctx = {
            "days": days,
            "cycle": cycle,
            "season": trip.season or "autumn",
            "temp_profile": trip.temp_profile or "mild",
            "avg_temp_c": trip.avg_temp_c,
            "precip_mm": trip.precip_mm,
            "snowfall_mm": trip.snowfall_mm,
            "carry_on_only": bool(trip.carry_on_only),
            "activities": [a for a in (trip.activities or "").split(",") if a],
        }
        out: List[Tuple[str, str, int]] = []
        for rule in self.rules.get("items", []):
            if cond_pass(rule.get("conditions", {}), ctx):
                calc = (rule.get("quantity") or {}).get("calc", "1")
                qty = self.evalr.eval(calc, ctx)
                out.append((rule["name"], rule["category"], qty))

        if self.rules.get("post_processing", {}).get("merge_duplicates", True):
            merged: Dict[Tuple[str, str], int] = {}
            for n, c, q in out:
                merged[(n, c)] = merged.get((n, c), 0) + q
            out = [(n, c, q) for (n, c), q in merged.items()]

        floor_min = int(self.rules.get("post_processing", {}).get("floor_min", 1))
        return [(n, c, max(floor_min, q)) for (n, c, q) in out]
