import cvxpy as cp

x = cp.Variable(nonneg=True, name="x")
y = cp.Variable(nonneg=True, name="y")

constraints = [
    # Constraint 0: x + 2y <= 14.
    x + 2 * y <= 14.0,
    # Constraint 1: 3x - y >= 0.
    3 * x - y >= 0.0,
    # Constraint 2: x - y <= 2.
    x - y <= 2.0,
    # Constraint 3: (x - 3)^2 + (y - 3)^2 <= 1 (exact, convex quadratic).
    cp.square(x - 3) + cp.square(y - 3) <= 1.0,
]

# Objective function: 3x + 4y.
problem = cp.Problem(cp.Maximize(3 * x + 3 * y), constraints)
problem.solve(solver=cp.CLARABEL)

print(f"Status: {problem.status}")
if problem.status == cp.OPTIMAL:
    print("Solution:")
    print(f"Objective value = {problem.value:0.4f}")
    print(f"x = {x.value:0.4f}")
    print(f"y = {y.value:0.4f}")
else:
    print("The problem does not have an optimal solution.")
