// LeadHunter AI — Dashboard Client Script

let allLeads = [];
let isDryRun = true;

document.addEventListener("DOMContentLoaded", () => {
    // Restore previous inputs or set defaults
    const savedCity = localStorage.getItem("leadhunter_city") || "Surat";
    const savedCategory = localStorage.getItem("leadhunter_category") || "Dentist";

    const cityInput = document.getElementById("targetCity");
    const catInput = document.getElementById("targetCategory");

    if (cityInput) {
        cityInput.value = savedCity;
        cityInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                runStage("all");
            }
        });
    }

    if (catInput) {
        catInput.value = savedCategory;
        catInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                runStage("all");
            }
        });
    }

    refreshAllData();
    setInterval(fetchLiveLogs, 5000);
});

function handleParamChange() {
    const city = getCity();
    const category = getCategory();
    localStorage.setItem("leadhunter_city", city);
    localStorage.setItem("leadhunter_category", category);
    refreshAllData();
}

function getCity() {
    const el = document.getElementById("targetCity");
    return el && el.value.trim() ? el.value.trim() : "Surat";
}

function getCategory() {
    const el = document.getElementById("targetCategory");
    return el && el.value.trim() ? el.value.trim() : "Dentist";
}

// Tab Switching
function switchTab(tabId) {
    document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));

    const targetTab = document.getElementById(`tab-${tabId}`);
    if (targetTab) targetTab.classList.add("active");

    const targetNav = Array.from(document.querySelectorAll(".nav-item")).find(btn => 
        btn.getAttribute("onclick")?.includes(tabId)
    );
    if (targetNav) targetNav.classList.add("active");

    if (tabId === "approval") loadApprovalQueue();
    if (tabId === "leads") loadLeadsTable();
    if (tabId === "logs") fetchLiveLogs();
}

// Toast Notifications
function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    const icon = type === "success" ? "✅" : type === "error" ? "❌" : "ℹ️";
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Refresh Global Data
async function refreshAllData() {
    const city = getCity();
    document.getElementById("displayCity").innerText = city;
    await Promise.all([fetchStats(), loadLeadsTable(), loadApprovalQueue(), fetchLiveLogs()]);
}

// Fetch Pipeline Stats
async function fetchStats() {
    try {
        const city = getCity();
        const res = await fetch(`/api/stats?city=${encodeURIComponent(city)}`);
        const data = await res.json();
        if (data.status === "ok") {
            const s = data.stats;
            document.getElementById("statDiscovered").innerText = s.discovered || 0;
            document.getElementById("statHot").innerText = s.hot || 0;
            document.getElementById("statWarm").innerText = s.warm || 0;
            document.getElementById("statDemoReady").innerText = s.demo_ready || 0;
            document.getElementById("statPendingApproval").innerText = s.pending_approval || 0;
            document.getElementById("statSent").innerText = (s.sent || 0) + (s.dry_run_sent || 0);

            // Update badge on sidebar
            document.getElementById("pendingApprovalBadge").innerText = s.pending_approval || 0;
        }
    } catch (err) {
        console.error("Error fetching stats:", err);
    }
}

// Execute Pipeline Stage
async function runStage(stage) {
    const city = getCity();
    const category = getCategory();
    showToast(`Triggering Stage: ${stage.toUpperCase()}...`, "info");

    try {
        const res = await fetch(`/api/pipeline/run-stage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ stage, city, category, limit: 10 })
        });
        const result = await res.json();
        if (result.status === "ok") {
            showToast(`Stage [${stage.toUpperCase()}] completed successfully!`, "success");
            await refreshAllData();
        } else {
            showToast(`Stage [${stage.toUpperCase()}] error: ${result.error}`, "error");
        }
    } catch (err) {
        showToast(`Failed to execute stage ${stage}: ${err}`, "error");
    }
}

// Toggle Dry Run Mode
async function toggleDryRun() {
    try {
        const res = await fetch(`/api/config/dry-run`, { method: "POST" });
        const data = await res.json();
        isDryRun = data.dry_run;

        const pill = document.getElementById("dryRunToggle");
        if (isDryRun) {
            pill.className = "mode-pill dry-run-active";
            pill.innerHTML = "🛡️ DRY RUN ACTIVE";
            showToast("Outreach Safety Mode: DRY_RUN enabled", "info");
        } else {
            pill.className = "mode-pill live-active";
            pill.innerHTML = "🚨 LIVE MODE ACTIVE";
            showToast("WARNING: Outreach Live Sending Enabled!", "error");
        }
    } catch (err) {
        console.error("Error toggling dry run:", err);
    }
}

// Load Approval Queue
async function loadApprovalQueue() {
    const container = document.getElementById("approvalQueueContainer");
    try {
        const city = getCity();
        const res = await fetch(`/api/approvals?city=${encodeURIComponent(city)}`);
        const data = await res.json();
        const leads = data.leads || [];

        if (leads.length === 0) {
            container.innerHTML = `<div class="empty-state">✅ All caught up! No leads currently pending human approval.</div>`;
            return;
        }

        container.innerHTML = leads.map(l => {
            const leadName = l.name || l.business_name || 'Prospect';
            const leadId = l.lead_id || l.id;
            const demoUrl = l.demo_url || '';
            return `
            <div class="approval-card">
                <div class="approval-header">
                    <div>
                        <div class="approval-name">${leadName}</div>
                        <div class="approval-meta">📍 ${l.city || 'Vadodara'} • 🏷️ ${l.category || 'Local Business'} • 📞 ${l.phone || 'No phone'}</div>
                    </div>
                    <span class="badge ${l.lead_tier === 'HOT' ? 'badge-hot' : 'badge-warm'}">${l.lead_tier || 'PROSPECT'} (${l.lead_score || l.score || 0} pts)</span>
                </div>

                <div class="msg-preview-box">
                    <div class="msg-preview-title">📧 Cold Email Pitch</div>
                    <div style="font-weight: 600; margin-bottom: 4px;">${l.email_subject || 'Website Proposal'}</div>
                    <div style="color: #94a3b8; font-size: 0.82rem; white-space: pre-line;">${(l.email_message || 'N/A').slice(0, 160)}...</div>
                </div>

                <div class="msg-preview-box">
                    <div class="msg-preview-title">📱 WhatsApp Copy</div>
                    <div style="color: #94a3b8; font-size: 0.82rem; white-space: pre-line;">${(l.whatsapp_message || 'N/A').slice(0, 140)}...</div>
                </div>

                <div class="flex items-center justify-between" style="font-size: 0.82rem;">
                    <span>Demo Preview:</span>
                    ${demoUrl ? `<button class="btn btn-outline btn-sm" onclick="openDemoModal('${demoUrl}', '${escapeQuotes(leadName)}')">🖥️ View Demo Page</button>` : `<span style="color: #64748b;">Not Generated</span>`}
                </div>

                <div class="approval-actions">
                    <button class="btn btn-success" onclick="reviewLead(${leadId}, 'APPROVE')">✅ Approve</button>
                    <button class="btn btn-danger" onclick="reviewLead(${leadId}, 'REJECT')">❌ Reject</button>
                    ${l.phone ? `<button class="btn btn-outline btn-sm" onclick="openWhatsAppDirect('${l.phone}', '${escapeQuotes(l.whatsapp_message || '')}', '${demoUrl}')" style="margin-left: auto; border-color: #22c55e; color: #22c55e;">💬 Open in WhatsApp</button>` : ''}
                </div>
            </div>
            `;
        }).join("");

    } catch (err) {
        container.innerHTML = `<div class="empty-state">Error loading approval queue: ${err}</div>`;
    }
}

// 1-Click Review Lead
async function reviewLead(leadId, decision) {
    try {
        const res = await fetch(`/api/approvals/${leadId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ decision })
        });
        const result = await res.json();
        if (result.status === "ok") {
            showToast(`Lead [ID ${leadId}] marked ${decision}D!`, "success");
            await loadApprovalQueue();
            await fetchStats();
        }
    } catch (err) {
        showToast(`Failed to update approval: ${err}`, "error");
    }
}

// Approve All Pending
async function approveAllPending() {
    try {
        const city = getCity();
        const res = await fetch(`/api/approvals/approve-all?city=${encodeURIComponent(city)}`, { method: "POST" });
        const result = await res.json();
        showToast(`Approved ${result.count || 0} pending leads!`, "success");
        await loadApprovalQueue();
        await fetchStats();
    } catch (err) {
        showToast(`Error: ${err}`, "error");
    }
}

// Load Leads Explorer Table
async function loadLeadsTable() {
    try {
        const city = getCity();
        const res = await fetch(`/api/leads?city=${encodeURIComponent(city)}`);
        const data = await res.json();
        allLeads = data.leads || [];
        renderLeadsTable(allLeads);
        renderHotProspects(allLeads);
    } catch (err) {
        console.error("Error loading leads table:", err);
    }
}

function renderHotProspects(leads) {
    const list = document.getElementById("hotProspectsList");
    const hotLeads = leads.filter(l => l.lead_tier === "HOT").slice(0, 4);

    if (hotLeads.length === 0) {
        list.innerHTML = `<div class="empty-state">No HOT leads detected yet. Run Scoring stage!</div>`;
        return;
    }

    list.innerHTML = hotLeads.map(l => `
        <div class="compact-lead-card">
            <div>
                <div class="compact-lead-title">${l.name}</div>
                <div class="compact-lead-meta">📍 ${l.city} • Website: ${l.website_status || 'Unchecked'}</div>
            </div>
            <div class="flex items-center gap-2">
                <span class="badge badge-hot">${l.score || 0} pts</span>
                ${l.demo_url ? `<button class="btn btn-outline btn-sm" onclick="openDemoModal('${l.demo_url}', '${escapeQuotes(l.name)}')">Demo</button>` : ''}
            </div>
        </div>
    `).join("");
}

function renderLeadsTable(leads) {
    const tbody = document.getElementById("leadsTableBody");
    if (leads.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center">No leads found matching criteria.</td></tr>`;
        return;
    }

    tbody.innerHTML = leads.map(l => `
        <tr>
            <td><strong>#${l.id}</strong></td>
            <td><strong>${l.name}</strong></td>
            <td>${l.category || '-'}</td>
            <td>${l.city}</td>
            <td><span class="badge badge-info">${l.website_status || 'PENDING'}</span></td>
            <td>
                ${l.lead_tier ? `<span class="badge ${l.lead_tier === 'HOT' ? 'badge-hot' : l.lead_tier === 'WARM' ? 'badge-warm' : 'badge-low'}">${l.lead_tier} (${l.score || 0})</span>` : '-'}
            </td>
            <td><span class="badge ${l.status === 'SENT' || l.status === 'DRY_RUN_SENT' ? 'badge-success' : 'badge-low'}">${l.status}</span></td>
            <td>
                ${l.demo_url ? `<button class="btn btn-outline btn-sm" onclick="openDemoModal('${l.demo_url}', '${escapeQuotes(l.name)}')">🖥️ View Demo</button>` : `<span style="color: #64748b;">—</span>`}
            </td>
            <td>
                <button class="btn btn-outline btn-sm" onclick="openLeadModal(${l.id})">🔍 Details</button>
            </td>
        </tr>
    `).join("");
}

// Search and Filter Leads Table
function filterLeadsTable() {
    const query = document.getElementById("leadSearchInput").value.toLowerCase().trim();
    const tier = document.getElementById("filterTier").value;
    const status = document.getElementById("filterStatus").value;
    const webStatus = document.getElementById("filterWebsiteStatus").value;

    const filtered = allLeads.filter(l => {
        const matchesQuery = !query || 
            l.name.toLowerCase().includes(query) || 
            (l.phone && l.phone.toLowerCase().includes(query)) ||
            (l.address && l.address.toLowerCase().includes(query));
        const matchesTier = !tier || l.lead_tier === tier;
        const matchesStatus = !status || l.status === status;
        const matchesWeb = !webStatus || l.website_status === webStatus;
        return matchesQuery && matchesTier && matchesStatus && matchesWeb;
    });

    renderLeadsTable(filtered);
}

function formatPhoneForWhatsApp(phone) {
    if (!phone) return "";
    let digits = phone.replace(/\D/g, "");
    if (digits.length === 10) return "91" + digits;
    if (digits.length === 11 && digits.startsWith("0")) return "91" + digits.slice(1);
    if (digits.length >= 10 && !digits.startsWith("91")) return "91" + digits;
    return digits;
}

function openWhatsAppDirect(phone, messageText, demoUrl) {
    const formattedPhone = formatPhoneForWhatsApp(phone);
    if (!formattedPhone) {
        showToast("Invalid or missing phone number for WhatsApp", "error");
        return;
    }
    let body = messageText || `Hi! Check out your website demo: ${demoUrl}`;
    if (demoUrl && !body.includes(demoUrl)) {
        body += `\n\nPreview Link: ${demoUrl}`;
    }
    const url = `https://wa.me/${formattedPhone}?text=${encodeURIComponent(body)}`;
    window.open(url, "_blank");
}

function escapeQuotes(str) {
    if (!str) return "";
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function formatDemoUrl(rawUrl) {
    if (!rawUrl) return "";
    if (rawUrl.includes("/preview/")) {
        return "/preview/" + rawUrl.split("/preview/")[1];
    }
    return rawUrl;
}

// Open Demo Preview Modal
function openDemoModal(demoUrl, title) {
    const cleanUrl = formatDemoUrl(demoUrl);
    const displayTitle = title && title !== "undefined" ? title : "Demo Website";
    document.getElementById("modalDemoTitle").innerText = displayTitle;
    document.getElementById("modalDemoExternalLink").href = cleanUrl;
    document.getElementById("demoPreviewFrame").src = cleanUrl;
    document.getElementById("demoModal").classList.add("show");
}

// Open Lead Detail Modal
async function openLeadModal(leadId) {
    const modal = document.getElementById("leadModal");
    const body = document.getElementById("modalLeadBody");
    modal.classList.add("show");
    body.innerHTML = "Loading lead profile...";

    try {
        const res = await fetch(`/api/leads/${leadId}`);
        const data = await res.json();
        const l = data.lead;

        document.getElementById("modalLeadName").innerText = l.name;
        body.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 14px;">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div><strong>📍 City:</strong> ${l.city}</div>
                    <div><strong>🏷️ Category:</strong> ${l.category || '-'}</div>
                    <div><strong>📞 Phone:</strong> ${l.phone || 'N/A'}</div>
                    <div><strong>✉️ Email:</strong> ${l.email || 'N/A'}</div>
                    <div><strong>🌐 Website:</strong> ${l.website ? `<a href="${l.website}" target="_blank" style="color:#f97316;">${l.website}</a>` : 'None'}</div>
                    <div><strong>⭐ Rating:</strong> ${l.rating || 'N/A'} (${l.reviews_count || 0} reviews)</div>
                </div>

                <div class="msg-preview-box">
                    <div class="msg-preview-title">📊 Qualification Score Reasons</div>
                    <ul style="padding-left: 18px; color: #94a3b8; font-size: 0.82rem;">
                        ${(l.score_reasons || []).map(r => `<li>${r}</li>`).join('') || '<li>No reasons recorded</li>'}
                    </ul>
                </div>

                <div class="msg-preview-box">
                    <div class="msg-preview-title">📧 AI Cold Email</div>
                    <div style="font-weight:600; margin-bottom:4px;">Subject: ${l.email_subject || 'N/A'}</div>
                    <div style="color: #94a3b8; font-size: 0.82rem; white-space: pre-line;">${l.email_message || 'No email generated yet.'}</div>
                </div>

                <div class="msg-preview-box">
                    <div class="msg-preview-title">📱 AI WhatsApp Message</div>
                    <div style="color: #94a3b8; font-size: 0.82rem; white-space: pre-line;">${l.whatsapp_message || 'No WhatsApp message generated yet.'}</div>
                </div>
            </div>
        `;
    } catch (err) {
        body.innerHTML = `Error loading details: ${err}`;
    }
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove("show");
    if (modalId === "demoModal") {
        document.getElementById("demoPreviewFrame").src = "";
    }
}

function closeModalOnBackdrop(event, modalId) {
    if (event.target.id === modalId) {
        closeModal(modalId);
    }
}

// Fetch Live Console Logs
async function fetchLiveLogs() {
    try {
        const res = await fetch(`/api/logs?limit=40`);
        const data = await res.json();
        const logs = data.logs || [];

        // Update full console
        const consoleBox = document.getElementById("fullConsoleLogs");
        if (consoleBox) {
            consoleBox.innerHTML = `<pre class="console-text">${logs.join("\n")}</pre>`;
        }

        // Update overview preview stream
        const streamBox = document.getElementById("recentLogsStream");
        if (streamBox) {
            streamBox.innerHTML = logs.slice(-12).map(l => `<div class="log-line">${l}</div>`).join("");
        }
    } catch (err) {
        console.error("Error fetching logs:", err);
    }
}

function clearConsoleView() {
    document.getElementById("fullConsoleLogs").innerHTML = `<pre class="console-text">[Cleared console view]</pre>`;
}

function exportToCsv() {
    window.open(`/api/export/csv?city=${encodeURIComponent(getCity())}`, "_blank");
}
