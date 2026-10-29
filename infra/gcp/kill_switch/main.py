"""Detach billing from the project once actual spend reaches the budget.

Budget notifications arrive on Pub/Sub several times a day. Most are below the
limit and are ignored. Detaching billing stops every paid service in the project,
including Cloud SQL; re-link the billing account in the console to start again.
"""

import base64
import json
import os

import functions_framework
from google.cloud import billing_v1


@functions_framework.cloud_event
def stop_billing(cloud_event) -> None:
    payload = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))
    cost = payload["costAmount"]
    budget = payload["budgetAmount"]
    if cost < budget:
        print(f"Spend {cost} is under budget {budget}; nothing to do.")
        return

    name = f"projects/{os.environ['PROJECT_ID']}"
    client = billing_v1.CloudBillingClient()
    info = client.get_project_billing_info(name=name)
    if not info.billing_enabled:
        print("Billing is already disabled.")
        return

    client.update_project_billing_info(
        name=name,
        project_billing_info=billing_v1.ProjectBillingInfo(billing_account_name=""),
    )
    print(f"Spend {cost} reached budget {budget}; billing detached from {name}.")
