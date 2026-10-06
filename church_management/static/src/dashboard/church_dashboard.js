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
            activeChartTab: "attendance", // attendance | growth | services
            hoveredPoint: null,
            hoveredSlice: null,
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

    setChartTab(chartTab) {
        this.state.activeChartTab = chartTab;
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

    // ── Graph & Chart Calculations (Line, Bar, Pie / Donut) ─────────

    get kpi() {
        return this.state.data?.kpi || {};
    }

    get charts() {
        return this.state.data?.charts || {};
    }

    get tables() {
        return this.state.data?.tables || {};
    }

    // LINE CHART: Attendance Points & Smooth Curved Path
    get lineChartData() {
        const trend = this.charts.attendance_trend || [];
        if (!trend.length) return { points: [], linePath: "", areaPath: "", maxVal: 100 };

        const width = 600;
        const height = 200;
        const padding = 30;

        const maxVal = Math.max(...trend.map(t => t.people || 0), 10);
        const chartHeight = height - padding * 2;
        const stepX = (width - padding * 2) / Math.max(trend.length - 1, 1);

        const points = trend.map((t, i) => {
            const x = padding + i * stepX;
            const y = height - padding - (t.people / maxVal) * chartHeight;
            return {
                x: Math.round(x * 10) / 10,
                y: Math.round(y * 10) / 10,
                label: t.label || t.week,
                people: t.people,
            };
        });

        // Generate Smooth Bezier Curve Line Path
        let linePath = `M ${points[0].x} ${points[0].y}`;
        for (let i = 0; i < points.length - 1; i++) {
            const p0 = points[i];
            const p1 = points[i + 1];
            const cx1 = p0.x + (p1.x - p0.x) / 2;
            const cy1 = p0.y;
            const cx2 = p0.x + (p1.x - p0.x) / 2;
            const cy2 = p1.y;
            linePath += ` C ${cx1} ${cy1}, ${cx2} ${cy2}, ${p1.x} ${p1.y}`;
        }

        const areaPath = `${linePath} L ${points[points.length - 1].x} ${height - padding} L ${points[0].x} ${height - padding} Z`;

        return { points, linePath, areaPath, maxVal, width, height, padding };
    }

    // PIE / DOUGHNUT CHART 1: Membership Lifecycle Donut Slices
    get membershipDonutSlices() {
        const data = this.charts.status_distribution || [];
        return this._buildDonutSlices(data, 100, 100, 75, 45);
    }

    // PIE / DOUGHNUT CHART 2: Care Distribution Donut Slices
    get careDonutSlices() {
        const data = this.charts.care_distribution || [];
        return this._buildDonutSlices(data, 100, 100, 75, 45);
    }

    _buildDonutSlices(items, cx, cy, outerRadius, innerRadius) {
        const total = items.reduce((acc, item) => acc + (item.count || 0), 0);
        if (!total) return [];

        let currentAngle = -Math.PI / 2; // Start from top
        const slices = [];

        items.forEach((item) => {
            if (!item.count) return;
            const sliceAngle = (item.count / total) * 2 * Math.PI;
            const endAngle = currentAngle + sliceAngle;

            // Coordinates for outer arc
            const x1 = cx + outerRadius * Math.cos(currentAngle);
            const y1 = cy + outerRadius * Math.sin(currentAngle);
            const x2 = cx + outerRadius * Math.cos(endAngle);
            const y2 = cy + outerRadius * Math.sin(endAngle);

            // Coordinates for inner arc
            const x3 = cx + innerRadius * Math.cos(endAngle);
            const y3 = cy + innerRadius * Math.sin(endAngle);
            const x4 = cx + innerRadius * Math.cos(currentAngle);
            const y4 = cy + innerRadius * Math.sin(currentAngle);

            const largeArcFlag = sliceAngle > Math.PI ? 1 : 0;

            const path = `M ${x1} ${y1} A ${outerRadius} ${outerRadius} 0 ${largeArcFlag} 1 ${x2} ${y2} L ${x3} ${y3} A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 0 ${x4} ${y4} Z`;

            const pct = Math.round((item.count / total) * 100);

            slices.push({
                label: item.label,
                count: item.count,
                color: item.color,
                pct: pct,
                path: path,
            });

            currentAngle = endAngle;
        });

        return slices;
    }

    // BAR CHART: Max values for scaling
    get maxMonthlyGrowth() {
        const list = this.charts.monthly_growth || [];
        if (!list.length) return 10;
        const max = Math.max(...list.map(m => m.count || 0));
        return max > 0 ? max : 10;
    }

    get maxServiceAttendance() {
        const list = this.charts.service_types || [];
        if (!list.length) return 100;
        const max = Math.max(...list.map(s => s.attendance || 0));
        return max > 0 ? max : 100;
    }

    get maxCellGroupCount() {
        const list = this.charts.cell_groups || [];
        if (!list.length) return 20;
        const max = Math.max(...list.map(g => g.count || 0));
        return max > 0 ? max : 20;
    }
}

registry.category("actions").add("church_dashboard_main", ChurchAdminDashboard);
