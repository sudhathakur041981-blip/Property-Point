const loginPanel = document.getElementById("loginPanel");
const dashboard = document.getElementById("dashboard");
const loginForm = document.getElementById("loginForm");
const loginStatus = document.getElementById("loginStatus");
const dashboardStatus = document.getElementById("dashboardStatus");
const propertyList = document.getElementById("propertyList");
const enquiryList = document.getElementById("enquiryList");
const propertiesEmpty = document.getElementById("propertiesEmpty");
const enquiriesEmpty = document.getElementById("enquiriesEmpty");
const pendingCount = document.getElementById("pendingCount");
const enquiryCount = document.getElementById("enquiryCount");
let csrfToken = "";

async function adminApi(path, { method = "GET", payload, csrf = false } = {}) {
    const headers = {};
    if (payload !== undefined) {
        headers["Content-Type"] = "application/json";
    }
    if (csrf) {
        headers["X-CSRF-Token"] = csrfToken;
    }

    let response;
    try {
        response = await fetch(window.propertyPointApiUrl(path), {
            method,
            headers,
            credentials: "include",
            body: payload === undefined ? undefined : JSON.stringify(payload)
        });
    } catch {
        throw new Error("Can't reach the backend. Start it with `python server.py`.");
    }

    let result;
    try {
        result = await response.json();
    } catch {
        throw new Error("The server returned an invalid response.");
    }
    if (!response.ok || !result.ok) {
        const error = new Error(
            result.error?.message || "The admin request failed."
        );
        error.status = response.status;
        if (response.status === 401) {
            showLogin("Your admin session has expired. Please sign in again.");
        }
        throw error;
    }
    return result.data;
}

function setStatus(element, message, state = "") {
    element.textContent = message;
    element.dataset.state = state;
}

function showLogin(message = "") {
    csrfToken = "";
    dashboard.hidden = true;
    loginPanel.hidden = false;
    setStatus(loginStatus, message, message ? "error" : "");
}

function showDashboard(session) {
    loginPanel.hidden = true;
    dashboard.hidden = false;
    document.getElementById("signedInUsername").textContent = session.username;
    csrfToken = session.csrfToken;
    setStatus(loginStatus, "");
}

function addText(parent, tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    element.textContent = text;
    parent.appendChild(element);
    return element;
}

function formatPrice(price, purpose) {
    const formatted = new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 2
    }).format(price);
    return purpose === "Rent" ? `${formatted} / month` : formatted;
}

function addPhoneLink(parent, phone) {
    const link = document.createElement("a");
    link.href = `tel:${phone}`;
    link.textContent = phone;
    link.className = "admin-phone";
    parent.appendChild(link);
}

function propertyCard(property) {
    const card = document.createElement("article");
    card.className = "admin-record";
    const heading = document.createElement("div");
    heading.className = "admin-record-heading";
    addText(heading, "h3", "", property.title);
    addText(
        heading,
        "span",
        `admin-badge ${property.purpose === "Rent" ? "rent" : ""}`,
        property.purpose
    );
    card.appendChild(heading);

    addText(card, "p", "admin-record-location", `${property.propertyType} · ${property.location}`);
    addText(card, "p", "admin-record-price", formatPrice(property.expectedPrice, property.purpose));

    const details = [
        property.bedrooms,
        property.bathrooms,
        property.areaSqFt
            ? `${Number(property.areaSqFt).toLocaleString("en-IN")} sq.ft`
            : ""
    ].filter(Boolean);
    if (details.length) {
        addText(card, "p", "admin-record-details", details.join(" · "));
    }
    if (property.description) {
        addText(card, "p", "admin-record-description", property.description);
    }

    const owner = document.createElement("div");
    owner.className = "admin-record-owner";
    addText(owner, "strong", "", property.ownerName);
    addPhoneLink(owner, property.ownerPhone);
    addText(owner, "span", "", `Submitted ${new Date(property.createdAt).toLocaleString()}`);
    card.appendChild(owner);

    const actions = document.createElement("div");
    actions.className = "admin-record-actions";
    const approveButton = document.createElement("button");
    approveButton.type = "button";
    approveButton.className = "primary-btn";
    approveButton.textContent = "Approve listing";
    approveButton.addEventListener("click", () =>
        updateProperty(property.id, "approved", approveButton, rejectButton)
    );
    const rejectButton = document.createElement("button");
    rejectButton.type = "button";
    rejectButton.className = "admin-secondary-button admin-reject-button";
    rejectButton.textContent = "Reject";
    rejectButton.addEventListener("click", () =>
        updateProperty(property.id, "rejected", approveButton, rejectButton)
    );
    actions.append(approveButton, rejectButton);
    card.appendChild(actions);
    return card;
}

function enquiryCard(enquiry) {
    const card = document.createElement("article");
    card.className = "admin-record";
    const heading = document.createElement("div");
    heading.className = "admin-record-heading";
    addText(heading, "h3", "", enquiry.name);
    addText(heading, "span", "admin-badge", `Looking to ${enquiry.requirement}`);
    if (enquiry.classification) {
        const isHot = enquiry.classification.includes("Hot");
        const scoreBadge = addText(heading, "span", "admin-badge", `${enquiry.classification} (${enquiry.leadScore || 25})`);
        if (isHot) {
            scoreBadge.style.background = "#fee2e2";
            scoreBadge.style.color = "#dc2626";
            scoreBadge.style.fontWeight = "800";
        }
    }
    card.appendChild(heading);
    addPhoneLink(card, enquiry.phone);
    if (enquiry.propertyInterest) {
        addText(card, "p", "admin-record-location", `Interested in: ${enquiry.propertyInterest}`);
    }
    addText(card, "p", "admin-record-details", `Received ${new Date(enquiry.createdAt).toLocaleString()}`);
    return card;
}

async function loadProperties() {
    setStatus(dashboardStatus, "Loading property submissions...");
    try {
        const response = await adminApi(
            "/api/admin/property-submissions?status=pending&limit=100"
        );
        propertyList.replaceChildren(...response.items.map(propertyCard));
        pendingCount.textContent = String(response.total);
        propertiesEmpty.hidden = response.items.length !== 0;
        setStatus(dashboardStatus, "");
    } catch (error) {
        if (!dashboard.hidden) {
            setStatus(dashboardStatus, error.message, "error");
        }
    }
}

async function loadEnquiries() {
    setStatus(dashboardStatus, "Loading customer enquiries...");
    try {
        const response = await adminApi("/api/admin/enquiries?limit=100");
        enquiryList.replaceChildren(...response.items.map(enquiryCard));
        enquiryCount.textContent = String(response.total);
        enquiriesEmpty.hidden = response.items.length !== 0;
        setStatus(dashboardStatus, "");
    } catch (error) {
        if (!dashboard.hidden) {
            setStatus(dashboardStatus, error.message, "error");
        }
    }
}

async function updateProperty(id, status, approveButton, rejectButton) {
    approveButton.disabled = true;
    rejectButton.disabled = true;
    setStatus(dashboardStatus, "Saving review decision...");
    try {
        await adminApi(`/api/admin/property-submissions/${id}`, {
            method: "PATCH",
            payload: { status },
            csrf: true
        });
        setStatus(
            dashboardStatus,
            status === "approved"
                ? "Listing approved and now public."
                : "Submission rejected.",
            "success"
        );
        await loadProperties();
    } catch (error) {
        approveButton.disabled = false;
        rejectButton.disabled = false;
        setStatus(dashboardStatus, error.message, "error");
    }
}

loginForm.addEventListener("submit", async event => {
    event.preventDefault();
    const submitButton = loginForm.querySelector('[type="submit"]');
    submitButton.disabled = true;
    setStatus(loginStatus, "Signing in...");
    try {
        const session = await adminApi("/api/admin/login", {
            method: "POST",
            payload: {
                username: document.getElementById("adminUsername").value.trim(),
                password: document.getElementById("adminPassword").value
            }
        });
        loginForm.reset();
        showDashboard(session);
        await Promise.all([loadProperties(), loadEnquiries()]);
    } catch (error) {
        setStatus(loginStatus, error.message, "error");
    } finally {
        submitButton.disabled = false;
    }
});

document.getElementById("logoutButton").addEventListener("click", async () => {
    const button = document.getElementById("logoutButton");
    button.disabled = true;
    try {
        await adminApi("/api/admin/logout", {
            method: "POST",
            payload: {},
            csrf: true
        });
        showLogin("You have signed out.");
    } catch (error) {
        setStatus(dashboardStatus, error.message, "error");
    } finally {
        button.disabled = false;
    }
});

document.getElementById("refreshProperties").addEventListener("click", loadProperties);
document.getElementById("refreshEnquiries").addEventListener("click", loadEnquiries);

document.querySelectorAll(".admin-tab").forEach(tab => {
    tab.addEventListener("click", () => {
        document.querySelectorAll(".admin-tab").forEach(otherTab => {
            const selected = otherTab === tab;
            otherTab.classList.toggle("active", selected);
            otherTab.setAttribute("aria-selected", String(selected));
        });
        document.querySelectorAll(".admin-panel").forEach(panel => {
            panel.hidden = panel.id !== tab.dataset.panel;
        });
    });
});

async function restoreSession() {
    try {
        const session = await adminApi("/api/admin/session");
        showDashboard(session);
        await Promise.all([loadProperties(), loadEnquiries()]);
    } catch (error) {
        if (error.status === 401) {
            showLogin();
        } else {
            showLogin(error.message);
        }
    }
}

restoreSession();
