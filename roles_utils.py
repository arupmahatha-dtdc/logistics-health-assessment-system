def _allowed_child_roles(current_role: str) -> list:
    if current_role == "Admin":
        return ["Admin", "Zone", "Region", "City", "Branch"]
    if current_role == "Zone":
        return ["Region", "City", "Branch"]
    if current_role == "Region":
        return ["City", "Branch"]
    if current_role == "City":
        return ["Branch"]
    return []


