/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class ChurchAdminDashboard extends Component {
    static template = "church_management.AdminDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            activeTab: "overview", // overview | members | care | attendance | community
            data: null,
            searchQuery: "",
            filterPeriod: "all",
            refreshing: false,
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        this.state.loading = true;
        try {
            const res = await this.orm.call("church.dashboard", "get_admin_dashboard_data", [], {
                period: this.state.filterPeriod,
            });
            if (res && res.success) {
                this.state.data = res;
            } else {
                this.notification.add(_t("Could not load dashboard metrics"), { type: "danger" });
            }
        } catch (error) {
            console.error("Error loading church admin dashboard:", error);
            this.notification.add(_t("Error loading dashboard data"), { type: "danger" });
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    async refresh() {
        this.state.refreshing = true;
        await this.loadDashboardData();
        this.notification.add(_t("Dashboard refreshed"), { type: "success" });
    }

    setTab(tabName) {
        this.state.activeTab = tabName;
    }

    // ── Navigation & Click Actions ──────────────────────────────────

    openMembers(domain = null, title = null) {
        const finalDomain = domain || [["is_member", "=", true]];
        this.actionService.doAction({
            name: title || _t("Church Members"),
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [
                [false, "list"],
                [false, "form"],
                [false, "kanban"],
            ],
            domain: finalDomain,
            context: { default_is_member: true },
        });
    }

    openActiveMembers() {
        this.openMembers(
            [["is_member", "=", true], ["membership_status", "in", ["new_convert", "member", "worker", "leader"]]],
            _t("Active Church Members")
        );
    }

    openNewMembersThisMonth() {
        this.openMembers(
            [["is_member", "=", true]],
            _t("Members Directory")
        );
    }

    openVisitors() {
        this.actionService.doAction({
            name: _t("Visitors"),
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["visitor_stage", "!=", false]],
            context: { group_by: "visitor_stage" },
        });
    }

    openRelativesToVerify() {
        this.actionService.doAction({
            name: _t("Relatives to Verify"),
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["family_verified", "=", false]],
        });
    }

    openFamilies() {
        this.actionService.doAction({
            name: _t("Families"),
            type: "ir.actions.act_window",
            res_model: "church.family",
            views: [
                [false, "list"],
                [false, "form"],
            ],
        });
    }

    openCellGroups() {
        this.actionService.doAction({
            name: _t("Cell Groups"),
            type: "ir.actions.act_window",
            res_model: "cell.group",
            views: [
                [false, "list"],
                [false, "form"],
            ],
        });
    }

    openCellGroup(groupId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "cell.group",
            res_id: groupId,
            views: [[false, "form"]],
        });
    }

    openServices() {
        this.actionService.doAction({
            name: _t("Services & Events"),
            type: "ir.actions.act_window",
            res_model: "church.service",
            views: [
                [false, "list"],
                [false, "form"],
            ],
        });
    }

    openService(serviceId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "church.service",
            res_id: serviceId,
            views: [[false, "form"]],
        });
    }

    openAttendance() {
        this.actionService.doAction({
            name: _t("Attendance Records"),
            type: "ir.actions.act_window",
            res_model: "church.event.attendance",
            views: [
                [false, "list"],
                [false, "form"],
            ],
        });
    }

    openCareNotes() {
        this.actionService.doAction({
            name: _t("Pastoral Care Notes"),
            type: "ir.actions.act_window",
            res_model: "pastoral.care.note",
            views: [
                [false, "list"],
                [false, "form"],
            ],
        });
    }

    openCareMembers(careStatus = null) {
        const domain = [["is_member", "=", true]];
        if (careStatus) {
            domain.push(["care_status", "=", careStatus]);
        } else {
            domain.push(["care_status", "in", ["needs_follow_up", "at_risk", "hospitalized", "bereavement", "counseling", "prayer_needed"]]);
        }
        this.actionService.doAction({
            name: careStatus ? _t(`Care: ${careStatus}`) : _t("Members Needing Care Attention"),
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: domain,
        });
    }

    openPrayerRequests(filter = null) {
        const domain = [];
        let title = _t("Prayer Requests");
        if (filter === "open") {
            domain.push(["care_status", "in", ["submitted", "assigned", "praying", "follow_up"]]);
            title = _t("Open Prayer Requests");
        } else if (filter === "urgent") {
            domain.push(["care_status", "in", ["submitted", "assigned", "praying", "follow_up"]]);
            domain.push(["urgency", "in", ["urgent", "high"]]);
            title = _t("Urgent Prayer Requests");
        } else if (filter === "unassigned") {
            domain.push(["care_status", "in", ["submitted", "assigned", "praying", "follow_up"]]);
            domain.push(["assigned_pastor_id", "=", false]);
            title = _t("Unassigned Prayer Requests");
        }
        this.actionService.doAction({
            name: title,
            type: "ir.actions.act_window",
            res_model: "prayer.request",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: domain,
        });
    }

    openPrayerRequest(prayerId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "prayer.request",
            res_id: prayerId,
            views: [[false, "form"]],
        });
    }

    openPastorAssignments() {
        this.actionService.doAction({
            name: _t("Pastor Assignments"),
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            domain: [["staff_role", "=", "pastor"]],
            views: [
                [false, "list"],
                [false, "form"],
            ],
        });
    }

    openMember(memberId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: memberId,
            views: [[false, "form"]],
        });
    }

    // ── Quick Creation Modals ───────────────────────────────────────

    createMember() {
        this.actionService.doAction({
            name: _t("New Member"),
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [[false, "form"]],
            target: "new",
            context: { default_is_member: true, default_membership_status: "member" },
        });
    }

    createVisitor() {
        this.actionService.doAction({
            name: _t("New Visitor"),
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [[false, "form"]],
            target: "new",
            context: { default_membership_status: "visitor", default_visitor_stage: "new" },
        });
    }

    createService() {
        this.actionService.doAction({
            name: _t("Create Service / Event"),
            type: "ir.actions.act_window",
            res_model: "church.service",
            views: [[false, "form"]],
            target: "new",
        });
    }

    createCareNote(memberId = null) {
        const context = {};
        if (memberId) {
            context.default_member_id = memberId;
        }
        this.actionService.doAction({
            name: _t("Log Pastoral Care Note"),
            type: "ir.actions.act_window",
            res_model: "pastoral.care.note",
            views: [[false, "form"]],
            target: "new",
            context: context,
        });
    }

    createPrayerRequest() {
        this.actionService.doAction({
            name: _t("New Prayer Request"),
            type: "ir.actions.act_window",
            res_model: "prayer.request",
            views: [[false, "form"]],
            target: "new",
            context: { default_care_status: "submitted", default_visibility: "public" },
        });
    }

    createCellGroup() {
        this.actionService.doAction({
            name: _t("New Cell Group"),
            type: "ir.actions.act_window",
            res_model: "cell.group",
            views: [[false, "form"]],
            target: "new",
        });
    }

    // ── Helpers ─────────────────────────────────────────────────────

    get kpi() {
        return this.state.data?.kpi || {};
    }

    get charts() {
        return this.state.data?.charts || {};
    }

    get tables() {
        return this.state.data?.tables || {};
    }

    get maxTrendAttendance() {
        const trend = this.charts.attendance_trend || [];
        if (!trend.length) return 100;
        const max = Math.max(...trend.map(t => t.people || 0));
        return max > 0 ? max : 100;
    }

    get maxServiceAttendance() {
        const list = this.charts.service_types || [];
        if (!list.length) return 100;
        const max = Math.max(...list.map(s => s.attendance || 0));
        return max > 0 ? max : 100;
    }

    get filteredAbsentMembers() {
        const list = this.tables.absent_members || [];
        if (!this.state.searchQuery) return list;
        const q = this.state.searchQuery.toLowerCase();
        return list.filter(m => (m.name || '').toLowerCase().includes(q) || (m.phone || '').includes(q));
    }
}

registry.category("actions").add("church_dashboard_main", ChurchAdminDashboard);
