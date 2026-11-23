"""The groups SmallStack ships, declared like any app's (see apps/access).

Each names a job a staff member does, as the permissions it needs and no
more. They're created after ``migrate`` and kept in step with this file; an
administrator's additions are kept and shown as drift on the Access pages.
Membership is granted locally or mapped from a directory.
"""

from apps.access.registry import register_group

register_group(
    "Access reviewer",
    description="Reads who may do what and every change to it; changes nothing.",
    permissions=[
        "access.view_accessevent",
        "access.view_managedgroup",
        "access.view_accessreview",
        "access.view_accessreviewitem",
        "auth.view_group",
        "auth.view_permission",
        "accounts.view_user",
    ],
    app_label="smallstack",
)

register_group(
    "Access attester",
    description="Opens, decides and signs the periodic access review; changes no access itself.",
    permissions=[
        "accounts.view_user",
        "access.view_accessevent",
        "access.view_managedgroup",
        "access.view_accessreview",
        "access.view_accessreviewitem",
        "access.sign_accessreview",
        "auth.view_group",
    ],
    app_label="smallstack",
)

register_group(
    "User manager",
    description="Creates, edits and deactivates accounts and puts them in groups.",
    permissions=[
        "accounts.view_user",
        "accounts.add_user",
        "accounts.change_user",
        "auth.view_group",
        "access.view_accessevent",
    ],
    app_label="smallstack",
)

register_group(
    "Log reader",
    description="Reads captured logs and opens capture windows.",
    permissions=[
        "telemetry.view_logrecord",
        "telemetry.view_logcapturewindow",
        "telemetry.add_logcapturewindow",
        "telemetry.change_logcapturewindow",
    ],
    app_label="smallstack",
)

register_group(
    "Approver",
    description="Sees and decides approval requests.",
    permissions=[
        "smallstack_approvals.view_approvalrequest",
        "smallstack_approvals.change_approvalrequest",
    ],
    app_label="smallstack",
)

register_group(
    "Token manager",
    description="Issues and revokes API tokens for anyone.",
    permissions=[
        "smallstack.view_apitoken",
        "smallstack.add_apitoken",
        "smallstack.change_apitoken",
        "smallstack.delete_apitoken",
    ],
    app_label="smallstack",
)
