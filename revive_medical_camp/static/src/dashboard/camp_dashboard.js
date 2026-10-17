/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_MS = 30000;

export class CampDashboard extends Component {
    static template = "revive_medical_camp.CampDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.state = useState({ loading: true, refreshing: false, data: null, error: null, selection: null });

        onWillStart(() => this.load());
        onMounted(() => {
            // Live camps refresh by themselves; paused while the tab is hidden.
            this.timer = setInterval(() => {
                if (this.state.data && this.state.data.live && !document.hidden) {
                    this.load(true);
                }
            }, REFRESH_MS);
        });
        onWillUnmount(() => clearInterval(this.timer));
    }

    async load(silent = false) {
        if (silent) {
            this.state.refreshing = true;
        } else {
            this.state.loading = true;
        }
        try {
            const data = await this.orm.call("camp.dashboard", "get_dashboard", [], {
                camp_id: this.state.selection,
            });
            this.state.data = data;
            this.state.error = null;
            if (this.state.selection === null) {
                this.state.selection = data.mode === "all" ? "all" : data.camp_id;
            }
        } catch (error) {
            const message = (error && error.data && error.data.message) || (error && error.message) || String(error);
            this.state.error = message;
            if (silent) {
                this.notification.add(_t("Could not refresh the dashboard."), { type: "warning" });
            }
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    onPickCamp(ev) {
        const value = ev.target.value;
        this.state.selection = value === "all" ? "all" : parseInt(value, 10);
        this.load();
    }

    refresh() {
        this.load(true);
    }

    // ── Formatting ───────────────────────────────────────────

    num(value, digits = 0) {
        const number = Number(value || 0);
        return number.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }

    money(value) {
        const currency = (this.state.data && this.state.data.currency) || "";
        return `${currency} ${this.num(value)}`.trim();
    }

    minutes(value) {
        if (value === null || value === undefined) {
            return "—";
        }
        if (value < 60) {
            return `${Math.round(value)} min`;
        }
        if (value >= 1440) {
            // Visits left open from an earlier day: days and hours read better.
            const days = Math.floor(value / 1440);
            return `${days} d ${Math.floor((value - days * 1440) / 60)} h`;
        }
        const hours = Math.floor(value / 60);
        return `${hours} h ${Math.round(value - hours * 60)} min`;
    }

    date(value) {
        if (!value) {
            return "";
        }
        const parsed = new Date(`${value}T00:00:00`);
        return isNaN(parsed) ? value : parsed.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    }

    maxOf(rows, ...keys) {
        let max = 0;
        for (const row of rows || []) {
            for (const key of keys) {
                max = Math.max(max, Number(row[key] || 0));
            }
        }
        return max || 1;
    }

    pct(value, max) {
        const share = Math.max(0, Math.min(100, (Number(value || 0) * 100) / (max || 1)));
        return `${share.toFixed(1)}%`;
    }

    barStyle(value, max) {
        return `width: ${this.pct(value, max)}`;
    }

    columnStyle(value, max) {
        return `height: ${this.pct(value, max)}`;
    }

    progressStyle(percent) {
        return `width: ${Math.max(0, Math.min(100, Number(percent || 0)))}%`;
    }

    get campDomain() {
        const data = this.state.data;
        return data && data.mode === "camp" && data.camp_id ? [["camp_id", "=", data.camp_id]] : [];
    }

    get stateClass() {
        const header = this.state.data && this.state.data.header;
        return `o_camp_dash_state o_camp_dash_state_${(header && header.state) || "all"}`;
    }

    get budgetMax() {
        return this.maxOf(this.state.data.money.categories, "planned", "actual");
    }

    // ── Drill-down ───────────────────────────────────────────

    open(model, name, extraDomain = []) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            domain: [...this.campDomain, ...extraDomain],
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    openVisits(extraDomain, name) {
        this.open("camp.visit", name || _t("Patient flow"), extraDomain);
    }

    openVisit(visitId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "camp.visit",
            res_id: visitId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCamp(campId) {
        this.state.selection = campId;
        this.load();
    }

    openCampForm() {
        const data = this.state.data;
        if (data && data.camp_id) {
            this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "camp.camp",
                res_id: data.camp_id,
                views: [[false, "form"]],
                target: "current",
            });
        }
    }
}

registry.category("actions").add("camp_dashboard", CampDashboard);
