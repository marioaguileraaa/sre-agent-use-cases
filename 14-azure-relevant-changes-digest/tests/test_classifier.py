"""Classifier rules: levels, reasons and flags (offline)."""

import unittest

from support import AKS_APP, HUMAN, SUB, analyze, classify, load_tool, row

NSG = "microsoft.network/networksecuritygroups"


def nsg_rule(index, name, source, port, access="Allow", direction="Inbound"):
    base = f"properties.securityRules[{index}]"
    return {f"{base}.name": ("", name), f"{base}.properties.access": ("", access), f"{base}.properties.direction": ("", direction),
            f"{base}.properties.sourceAddressPrefix": ("", source), f"{base}.properties.destinationPortRange": ("", port),
            f"{base}.properties.protocol": ("", "Tcp"), f"{base}.properties.provisioningState": ("", "Succeeded")}


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()

    def test_nsg_rule_from_internet_to_rdp_is_high_and_internet_exposed(self):
        for source in ("Internet", "*", "0.0.0.0/0"):
            with self.subTest(source=source):
                c = classify(self.t, row(NSG, "nsg-app", changes=nsg_rule(0, "allow-rdp", source, "3389"),
                                         op="Microsoft.Network/networkSecurityGroups/securityRules/write"))
                self.assertEqual(c["level"], "high")
                self.assertIn("internet-exposed", c["flags"])
                self.assertIn("3389 (RDP)", c["reasons"][0])
                self.assertTrue(c["security"])
                self.assertNotIn("properties.securityRules[0].properties.provisioningState",
                                 [p["path"] for p in c["paths"] if p["level"] != "noise"])

    def test_removed_exposed_rule_by_automation_is_high_and_attributed_to_the_app(self):
        governance_app = "3f2c9e1a-6b4d-4c8e-9a7f-2d5b8c1e4f60"
        removed = {path: (new, "") for path, (_, new) in nsg_rule(0, "allow-rdp", "Internet", "3389").items()}
        c = classify(self.t, row(NSG, "nsg-app", changes=removed, by=governance_app, by_type="Application", client="PowerShell"))
        self.assertEqual((c["level"], c["actor_class"], c["client_class"]), ("high", "automation", "script"))
        self.assertEqual(c["reasons"][0], "Security rule allow-rdp removed (was Inbound Allow from Internet to 3389 (RDP))")
        self.assertNotIn("internet-exposed", c["flags"])
        self.assertEqual(self.t.actor_display(c, {"expected": {}})[0], governance_app)

    def test_nsg_rule_from_office_cidr_is_high_but_not_exposed(self):
        c = classify(self.t, row(NSG, "nsg-app", changes=nsg_rule(1, "allow-ssh-office", "198.51.100.0/24", "22")))
        self.assertEqual(c["level"], "high")
        self.assertNotIn("internet-exposed", c["flags"])
        self.assertTrue(c["reasons"][0].startswith("Security rule allow-ssh-office added"))

    def test_modified_rule_uses_current_rule_state_for_exposure(self):
        rid = f"/subscriptions/{SUB}/resourceGroups/rg-app/providers/{NSG}/nsg-app"
        current = [{"name": "allow-rdp", "properties": {"access": "Allow", "direction": "Inbound", "sourceAddressPrefix": "10.0.0.0/8",
                                                        "destinationPortRange": "3389"}},
                   {"name": "allow-ssh-office", "properties": {"access": "Allow", "direction": "Inbound", "sourceAddressPrefix": "*",
                                                               "destinationPortRange": "22"}}]
        changed = row(NSG, "nsg-app", changes={"properties.securityRules[1].properties.sourceAddressPrefix": ("198.51.100.0/24", "*")})
        c = classify(self.t, changed, nsg_rules={rid.lower(): current})
        self.assertEqual(c["level"], "high")
        self.assertIn("internet-exposed", c["flags"])
        self.assertIn("allow-ssh-office", c["reasons"][0])
        self.assertEqual(c["paths"][0]["shape"], "modified")

    def test_modified_rule_is_resolved_from_earlier_changes_when_the_array_shifted(self):
        rid = f"/subscriptions/{SUB}/resourceGroups/rg-app/providers/{NSG}/nsg-app"
        rows = [row(NSG, "nsg-app", changes=nsg_rule(0, "allow-rdp", "Internet", "3389"), ts="2026-11-06T10:39:24Z"),
                row(NSG, "nsg-app", changes=nsg_rule(1, "allow-ssh-office", "198.51.100.0/24", "22"), ts="2026-11-06T10:39:29Z"),
                row(NSG, "nsg-app", changes={"properties.securityRules[1].properties.sourceAddressPrefix": ("198.51.100.0/24", "*")},
                    ts="2026-11-06T10:43:19Z"),
                row(NSG, "nsg-app", changes={path: (new, "") for path, (_, new) in nsg_rule(0, "allow-rdp", "Internet", "3389").items()},
                    by="3f2c9e1a-6b4d-4c8e-9a7f-2d5b8c1e4f60", by_type="Application", client="PowerShell", ts="2026-11-06T11:30:20Z")]
        current = [{"name": "allow-ssh-office", "properties": {"access": "Allow", "direction": "Inbound", "sourceAddressPrefix": "*",
                                                               "destinationPortRange": "22"}}]
        analysis, *_ = analyze(self.t, rows, nsg_rules={rid.lower(): current})
        modified = next(c for c in analysis["changes"] if c["when"].minute == 43)
        self.assertEqual(modified["reasons"][0], "Inbound Allow from any source (*) to 22 (SSH) on rule allow-ssh-office")
        self.assertIn("internet-exposed", modified["flags"])

    def test_public_network_access_enabled_is_high(self):
        c = classify(self.t, row("microsoft.storage/storageaccounts", "stapp", changes={"properties.publicNetworkAccess": ("Disabled", "Enabled")}))
        self.assertEqual(c["level"], "high")
        self.assertIn("exposure increased", c["flags"])
        self.assertEqual(c["reasons"][0], "Public network access Disabled -> Enabled")

    def test_key_vault_default_action_deny_to_allow_is_high(self):
        c = classify(self.t, row("microsoft.keyvault/vaults", "kv-app", changes={"properties.networkAcls.defaultAction": ("Deny", "Allow")}))
        self.assertEqual(c["level"], "high")
        self.assertIn("exposure increased", c["flags"])
        self.assertIn("Deny -> Allow", c["reasons"][0])

    def test_shared_key_access_enabled_is_high(self):
        c = classify(self.t, row("microsoft.storage/storageaccounts", "stapp", changes={"properties.allowSharedKeyAccess": ("false", "true")}))
        self.assertEqual((c["level"], "exposure increased" in c["flags"]), ("high", True))

    def test_human_delete_chain_is_one_high_item(self):
        corr = "c0ffee00-0000-4000-8000-000000000001"
        rows = [row("microsoft.compute/virtualmachines", "vm1", "Delete", corr=corr, op="Microsoft.Compute/virtualMachines/delete"),
                row("microsoft.compute/disks", "vm1-os", "Delete", corr=corr),
                row("microsoft.network/networkinterfaces", "vm1-nic", "Delete", corr=corr)]
        analysis, *_ = analyze(self.t, rows)
        self.assertEqual(len(analysis["delete_chains"]), 1)
        chain = analysis["delete_chains"][0]
        self.assertEqual((chain["level"], chain["deleted"]), ("high", 3))
        items = [i for i in self.t.build_items(analysis) if i["kind"] == "delete"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["level"], "high")

    def test_platform_delete_in_managed_resource_group_is_low_and_summarized(self):
        rows = [row("microsoft.compute/virtualmachines/extensions", "aks-node/ext", "Delete", by=AKS_APP, by_type="Application",
                    client="Go SDK", rg="mc_rg-aks_westeurope", corr="c0ffee00-0000-4000-8000-000000000002")]
        analysis, *_ = analyze(self.t, rows, managed=("mc_rg-aks_westeurope",))
        change = analysis["changes"][0]
        self.assertEqual((change["level"], change["actor_class"]), ("low", "platform"))
        self.assertTrue(analysis["delete_chains"][0]["managed"])

    def test_human_delete_in_managed_resource_group_stays_high(self):
        c = classify(self.t, row("microsoft.compute/disks", "d1", "Delete", rg="mc_rg"), managed=("mc_rg",))
        self.assertEqual(c["level"], "high")

    def test_aks_autoscale_capacity_is_low(self):
        vmss = classify(self.t, row("microsoft.compute/virtualmachinescalesets", "aks-nodepool1-vmss", by="7319c514-987d-4e9b-ac3d-d38c4f427f4c",
                                    by_type="Application", client="Azure Container Service", rg="mc_rg",
                                    changes={"sku.capacity": ("3", "5")}), managed=("mc_rg",))
        self.assertEqual((vmss["level"], vmss["reasons"][0]), ("low", "platform autoscale (capacity)"))
        cluster = classify(self.t, row("microsoft.containerservice/managedclusters", "aks1", by="7319c514-987d-4e9b-ac3d-d38c4f427f4c",
                                       by_type="Application", client="Azure Container Service",
                                       changes={"properties.agentPoolProfiles[0].count": ("3", "4")}))
        self.assertEqual(cluster["level"], "low")

    def test_vm_size_modified_is_medium_with_readable_reason(self):
        c = classify(self.t, row("microsoft.compute/virtualmachines", "vm1", changes={"properties.hardwareProfile.vmSize": ("Standard_B2s", "Standard_D4s_v5")}))
        self.assertEqual(c["level"], "medium")
        self.assertEqual(c["reasons"][0], "VM size Standard_B2s -> Standard_D4s_v5")

    def test_disk_sku_and_size_changes_are_medium(self):
        sku = classify(self.t, row("microsoft.compute/disks", "d1", changes={"sku.name": ("Standard_LRS", "Premium_LRS"), "sku.tier": ("Standard", "Premium"),
                                                                              "properties.diskIOPSReadWrite": ("500", "120")}))
        self.assertEqual((sku["level"], sku["reasons"][0]), ("medium", "SKU Standard_LRS -> Premium_LRS"))
        self.assertEqual(sku["reasons"][-1], "configuration change")
        size = classify(self.t, row("microsoft.compute/disks", "d1", changes={"properties.diskSizeGB": ("4", "8")}))
        self.assertEqual(size["reasons"][0], "Disk size 4 GB -> 8 GB")

    def test_platform_metadata_paths_are_noise(self):
        c = classify(self.t, row("microsoft.keyvault/vaults", "kv", changes={"properties.provisioningState": ("Updating", "Succeeded"), "etag": ("a", "b"),
                                                                             "properties.lastModified": ("x", "y"), "systemData.lastModifiedAt": ("1", "2")},
                                 by="00000000-0000-4000-8000-0000000000aa", by_type="Application"))
        self.assertEqual(c["level"], "noise")
        self.assertFalse(c["security"])

    def test_arc_agent_inventory_is_noise_and_not_human(self):
        c = classify(self.t, row("microsoft.hybridcompute/machines", "arc-server-01", by=HUMAN, by_type="User", client="Unspecified", op="Unspecified",
                                 changes={"properties.storageProfile.disks[0].usedSpaceInBytes": ("1", "2"),
                                          "properties.detectedProperties.totalPhysicalMemoryInBytes": ("3", "4")}))
        self.assertEqual((c["level"], c["actor_class"]), ("noise", "platform"))
        self.assertEqual(c["reasons"], ["agent-reported inventory"])

    def test_tag_only_change_is_low(self):
        c = classify(self.t, row("microsoft.web/sites", "app1", changes={"tags.owner": ("", "platform-team")}))
        self.assertEqual((c["level"], c["reasons"]), ("low", ["tag change"]))
        nsg_tag = classify(self.t, row(NSG, "nsg1", changes={"tags.costCenter": ("1", "2")}))
        self.assertEqual(nsg_tag["level"], "low")

    def test_new_public_ip_is_high_and_new_key_vault_is_medium(self):
        pip = classify(self.t, row("microsoft.network/publicipaddresses", "pip1", "Create"))
        self.assertEqual((pip["level"], "exposure increased" in pip["flags"]), ("high", True))
        kv = classify(self.t, row("microsoft.keyvault/vaults", "kv1", "Create"))
        self.assertEqual(kv["level"], "medium")

    def test_expected_automation_is_one_level_lower_except_critical_deletes(self):
        pipeline = "11111111-2222-4333-8444-555555555555"
        update = classify(self.t, row("microsoft.storage/storageaccounts", "st1", by=pipeline, by_type="Application", client="Go SDK",
                                      changes={"properties.publicNetworkAccess": ("Disabled", "Enabled")}), expected={pipeline: "Terraform prod"})
        self.assertEqual((update["level"], update["actor_class"]), ("medium", "expected-automation"))
        delete = classify(self.t, row("microsoft.keyvault/vaults", "kv1", "Delete", by=pipeline, by_type="Application"), expected={pipeline: "Terraform prod"})
        self.assertEqual(delete["level"], "high")

    def test_human_portal_change_in_prod_is_at_least_medium(self):
        c = classify(self.t, row("microsoft.web/sites", "app1", client="Azure Portal", rg="rg-prod", changes={"tags.owner": ("a", "b")}), prod=("rg-prod",))
        self.assertEqual(c["level"], "medium")
        self.assertIn("click-ops in production", c["flags"])

    def test_first_party_application_with_guid_client_is_platform(self):
        app = "4c1a0e5f-1111-4222-8333-444455556666"
        c = classify(self.t, row("microsoft.azurearcdata/sqlserverinstances", "sql1", by=app, by_type="Application", client=app.upper(),
                                 changes={"properties.version": ("1", "2")}))
        self.assertEqual((c["actor_class"], c["client_class"], c["level"]), ("platform", "service", "low"))

    def test_duplicate_record_is_noise(self):
        sku = {"sku.name": ("Standard_LRS", "Premium_LRS")}
        rows = [row("microsoft.compute/disks", "d1", changes=sku, ts="2026-11-06T10:43:23Z"),
                row("microsoft.compute/disks", "d1", changes=sku, ts="2026-11-06T10:53:23Z")]
        analysis, *_ = analyze(self.t, rows)
        levels = sorted(c["level"] for c in analysis["changes"])
        self.assertEqual(levels, ["medium", "noise"])
        self.assertEqual(next(c for c in analysis["changes"] if c["level"] == "noise")["reasons"], ["duplicate change record"])

    def test_delete_and_activity_log_rows_reuse_the_arg_casing_of_the_same_resource(self):
        created = row("microsoft.network/publicipaddresses", "pip-temp-test", "Create", ts="2026-11-06T10:38:03Z")
        deleted = row("microsoft.network/publicipaddresses", "PIP-TEMP-TEST", "Delete", ts="2026-11-06T10:44:49Z")
        deleted.update(attributedBy="activity_log")
        orphan = row("microsoft.compute/virtualmachines", "VM-OLD", "Delete", ts="2026-11-06T10:50:00Z")
        analysis, *_ = analyze(self.t, [created, deleted, orphan])
        names = {c["change_type"] + ":" + c["resource_name"] for c in analysis["changes"]}
        self.assertEqual(names, {"Create:pip-temp-test", "Delete:pip-temp-test", "Delete:VM-OLD"})
        pip_delete = next(c for c in analysis["changes"] if c["change_type"] == "Delete" and c["resource_name"] == "pip-temp-test")
        self.assertEqual(pip_delete["resource_id"], created["targetResourceId"])
        self.assertIn(["pip-temp-test"], [d["resources"] for d in analysis["delete_chains"]])

    def test_actor_recovered_from_activity_log_turns_system_delete_into_human_delete(self):
        deleted = row("microsoft.network/publicipaddresses", "PIP-TEMP", "Delete", by="System", by_type="System", client="Unspecified")
        self.assertEqual(classify(self.t, dict(deleted))["level"], "low")
        deleted.update(changedBy=HUMAN, changedByType="User", attributedBy="activity_log")
        c = classify(self.t, deleted)
        self.assertEqual(c["level"], "high")
        self.assertIn("actor recovered from the Activity Log (Change Analysis recorded no actor)", c["reasons"])


if __name__ == "__main__":
    unittest.main()
