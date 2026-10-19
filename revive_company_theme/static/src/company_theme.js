/** @odoo-module **/
// Colour the backend by the company being worked in. The colours come from
// the server (ir.http session_info); switching company reloads the page, so
// this runs again for the new company.
import { session } from "@web/session";
import { user } from "@web/core/user";

function currentCompanyId() {
    try {
        if (user.activeCompany && user.activeCompany.id) {
            return user.activeCompany.id;
        }
    } catch {
        // Older layouts: fall back to the session below.
    }
    return session.user_companies && session.user_companies.current_company;
}

const themes = session.revive_company_themes || {};
const theme = themes[currentCompanyId()];
if (theme && theme.primary) {
    const root = document.documentElement;
    root.style.setProperty("--revive-primary", theme.primary);
    root.style.setProperty("--revive-primary-dark", theme.primary_dark);
    root.style.setProperty("--revive-primary-rgb", theme.primary_rgb);
    root.style.setProperty("--revive-secondary", theme.secondary || theme.primary);
    root.classList.add("o_revive_company_themed");
}
