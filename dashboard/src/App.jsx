import { useState, useEffect, useRef } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const API = "http://127.0.0.1:8080/api";

// ─── Mock data for standalone preview ────────────────────────
const MOCK_STATS = {
  total: 127, discovered: 23, analyzed: 18, pending_approval: 3,
  applied: 41, interviewing: 6, offer: 2, rejected: 19, skipped: 15
};

const MOCK_JOBS = [
  { id: "a1b2c3", title: "Senior Product Manager - AI", company: "Anthropic", location: "Remote / SF", status: "interviewing", match_score: 94, easy_apply: false, found_at: "2026-04-07T09:12:00", url: "#", ai_analysis: { recommendation: "strong_apply", highlights: ["AI domain expertise", "PM leadership at scale"], salary_estimate: "$180K–220K" } },
  { id: "d4e5f6", title: "Director of Product", company: "Zepto", location: "Bengaluru", status: "applied", match_score: 88, easy_apply: true, found_at: "2026-04-06T14:30:00", url: "#", ai_analysis: { recommendation: "apply", highlights: ["Quick commerce domain", "0→1 experience"], salary_estimate: "₹60–80 LPA" } },
  { id: "g7h8i9", title: "Head of AI Products", company: "PhonePe", location: "Bengaluru", status: "pending_approval", match_score: 91, easy_apply: false, found_at: "2026-04-08T08:45:00", url: "#", ai_analysis: { recommendation: "strong_apply", highlights: ["FinTech AI", "Scale experience"] } },
  { id: "j1k2l3", title: "VP Product - Growth", company: "Swiggy", location: "Bengaluru", status: "applied", match_score: 82, easy_apply: true, found_at: "2026-04-05T11:20:00", url: "#", ai_analysis: {} },
  { id: "m4n5o6", title: "Product Lead - GenAI", company: "Google DeepMind", location: "London", status: "skipped", match_score: 71, easy_apply: false, found_at: "2026-04-04T16:00:00", url: "#", ai_analysis: { recommendation: "consider" } },
  { id: "p7q8r9", title: "Chief Product Officer", company: "Razorpay", location: "Bengaluru", status: "offer", match_score: 95, easy_apply: false, found_at: "2026-03-28T10:00:00", url: "#", ai_analysis: { recommendation: "strong_apply" } },
  { id: "s1t2u3", title: "PM - Platform & Infrastructure", company: "CRED", location: "Bengaluru", status: "analyzed", match_score: 76, easy_apply: true, found_at: "2026-04-08T07:30:00", url: "#", ai_analysis: {} },
  { id: "v4w5x6", title: "Senior PM - Payments", company: "Juspay", location: "Bengaluru", status: "analyzed", match_score: 79, easy_apply: true, found_at: "2026-04-08T06:15:00", url: "#", ai_analysis: {} },
];

const MOCK_CHAT = [
  { role: "assistant", content: "I'm ready to help you analyze this role. What would you like to know about **Head of AI Products at PhonePe**?" },
];

// ─── Helpers ───────────────────────────────────────────────────
const STATUS_META = {
  discovered:       { color: "#64748b", bg: "rgba(100,116,139,0.15)", label: "Discovered" },
  analyzed:         { color: "#a78bfa", bg: "rgba(167,139,250,0.15)", label: "Analyzed" },
  pending_approval: { color: "#f59e0b", bg: "rgba(245,158,11,0.15)",  label: "⏳ Awaiting You" },
  ready_to_apply:   { color: "#60a5fa", bg: "rgba(96,165,250,0.15)",  label: "Ready" },
  applied:          { color: "#34d399", bg: "rgba(52,211,153,0.15)",  label: "Applied" },
  interviewing:     { color: "#38bdf8", bg: "rgba(56,189,248,0.15)",  label: "Interviewing" },
  offer:            { color: "#fbbf24", bg: "rgba(251,191,36,0.2)",   label: "🎉 Offer!" },
  rejected:         { color: "#f87171", bg: "rgba(248,113,113,0.12)", label: "Rejected" },
  skipped:          { color: "#475569", bg: "rgba(71,85,105,0.12)",   label: "Skipped" },
  apply_failed:     { color: "#fb923c", bg: "rgba(251,146,60,0.12)",  label: "Failed" },
};

const scoreColor = (s) => s >= 85 ? "#34d399" : s >= 70 ? "#fbbf24" : "#f87171";

const fmtDate = (d) => {
  if (!d) return "";
  const dt = new Date(d);
  const diff = Math.round((Date.now() - dt) / 60000);
  if (diff < 60) return `${diff}m ago`;
  if (diff < 1440) return `${Math.round(diff/60)}h ago`;
  return dt.toLocaleDateString("en-IN", { day:"numeric", month:"short" });
};

// ─── Components ────────────────────────────────────────────────

function StatusBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.discovered;
  return (
    <span style={{
      background: m.bg, color: m.color,
      border: `1px solid ${m.color}33`,
      padding: "2px 8px", borderRadius: 4,
      fontSize: 11, fontWeight: 600, letterSpacing: "0.04em",
      fontFamily: "'IBM Plex Mono', monospace",
    }}>{m.label}</span>
  );
}

function ScorePill({ score }) {
  if (!score) return null;
  const c = scoreColor(score);
  return (
    <span style={{
      background: `${c}18`, color: c, border: `1px solid ${c}44`,
      padding: "2px 8px", borderRadius: 4,
      fontSize: 11, fontWeight: 700, fontFamily: "'IBM Plex Mono', monospace",
    }}>{score}%</span>
  );
}

function StatCard({ label, value, color = "#c8d6e5", accent }) {
  return (
    <div style={{
      background: "#0f1923", border: "1px solid #1e2d3d",
      borderTop: `2px solid ${accent || color}`,
      borderRadius: 8, padding: "14px 18px", minWidth: 100,
    }}>
      <div style={{ fontSize: 26, fontWeight: 800, color, fontFamily: "'IBM Plex Mono', monospace" }}>{value}</div>
      <div style={{ fontSize: 11, color: "#4a6375", marginTop: 2, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</div>
    </div>
  );
}

function ChatPanel({ job, onClose }) {
  const [messages, setMessages] = useState(MOCK_CHAT);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg = { role: "user", content: input };
    setMessages(m => [...m, userMsg]);
    setInput("");
    setLoading(true);

    // In production, call API: POST /api/jobs/:id/chat
    await new Promise(r => setTimeout(r, 1200));
    const botMsg = {
      role: "assistant",
      content: `Great question about **${job?.company}**! Based on the JD and your profile, here's what I think: their AI team is growing fast and this role sits directly under the CPO. Your experience with recommendation systems at TechCorp is a strong match. The ₹60–75 LPA range is fair for this level in Bengaluru — I'd negotiate from ₹72 LPA upward given your 8+ years.`
    };
    setMessages(m => [...m, botMsg]);
    setLoading(false);
  };

  return (
    <div style={{
      position: "fixed", right: 0, top: 0, bottom: 0, width: 400,
      background: "#080e14", borderLeft: "1px solid #1e2d3d",
      display: "flex", flexDirection: "column", zIndex: 100,
      fontFamily: "'Inter', sans-serif",
    }}>
      {/* Header */}
      <div style={{ padding: "16px 20px", borderBottom: "1px solid #1e2d3d", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#c8d6e5" }}>💬 Job Chat</div>
          <div style={{ fontSize: 11, color: "#4a6375", marginTop: 2 }}>{job?.title} · {job?.company}</div>
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "#4a6375", fontSize: 18, cursor: "pointer" }}>✕</button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        {messages.map((m, i) => (
          <div key={i} style={{
            display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start",
          }}>
            <div style={{
              maxWidth: "85%",
              background: m.role === "user" ? "#1a3a5c" : "#0f1923",
              border: `1px solid ${m.role === "user" ? "#2563eb33" : "#1e2d3d"}`,
              borderRadius: 10, padding: "10px 14px",
              fontSize: 13, color: "#c8d6e5", lineHeight: 1.55,
            }}
              dangerouslySetInnerHTML={{ __html: m.content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') }}
            />
          </div>
        ))}
        {loading && (
          <div style={{ display: "flex" }}>
            <div style={{ background: "#0f1923", border: "1px solid #1e2d3d", borderRadius: 10, padding: "10px 14px" }}>
              <span style={{ color: "#4a6375", fontSize: 13 }}>Thinking…</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: 16, borderTop: "1px solid #1e2d3d", display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
          placeholder="Ask about salary, culture, interview prep…"
          style={{
            flex: 1, background: "#0f1923", border: "1px solid #1e2d3d",
            borderRadius: 8, padding: "10px 14px", color: "#c8d6e5",
            fontSize: 13, outline: "none", fontFamily: "inherit",
          }}
        />
        <button onClick={send} disabled={loading} style={{
          background: "#2563eb", border: "none", borderRadius: 8,
          width: 40, cursor: "pointer", color: "#fff", fontSize: 16,
          opacity: loading ? 0.5 : 1,
        }}>↑</button>
      </div>
    </div>
  );
}

function JobRow({ job, onSelect, onChat, selected }) {
  const m = STATUS_META[job.status] || STATUS_META.discovered;
  const analysis = job.ai_analysis || {};
  return (
    <div
      onClick={() => onSelect(job)}
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 140px 130px 80px 90px 80px",
        gap: 12, alignItems: "center",
        padding: "12px 20px",
        borderBottom: "1px solid #0f1923",
        background: selected ? "#0f1923" : "transparent",
        cursor: "pointer", transition: "background 0.15s",
        borderLeft: selected ? `3px solid #2563eb` : "3px solid transparent",
      }}
      onMouseEnter={e => !selected && (e.currentTarget.style.background = "#0a1520")}
      onMouseLeave={e => !selected && (e.currentTarget.style.background = "transparent")}
    >
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#c8d6e5" }}>{job.title}</div>
        <div style={{ fontSize: 12, color: "#4a6375", marginTop: 2 }}>{job.company} · {job.location}</div>
      </div>
      <StatusBadge status={job.status} />
      <div style={{ fontSize: 12, color: "#4a6375" }}>{fmtDate(job.found_at)}</div>
      <ScorePill score={job.match_score} />
      <div style={{ fontSize: 11, color: "#4a6375" }}>
        {job.easy_apply ? <span style={{ color: "#34d399" }}>⚡ Easy</span> : <span>🌐 External</span>}
      </div>
      <button
        onClick={e => { e.stopPropagation(); onChat(job); }}
        style={{
          background: "#0f1923", border: "1px solid #1e2d3d",
          borderRadius: 6, padding: "4px 10px", fontSize: 11,
          color: "#4a6375", cursor: "pointer",
        }}
      >Chat ↗</button>
    </div>
  );
}

function PendingApprovalBanner({ jobs }) {
  if (!jobs.length) return null;
  return (
    <div style={{
      background: "linear-gradient(135deg, #1a120200, #2d1f00)",
      border: "1px solid #f59e0b44",
      borderRadius: 8, padding: "14px 20px",
      marginBottom: 16, display: "flex", alignItems: "center", gap: 16,
    }}>
      <div style={{ fontSize: 24 }}>📱</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#f59e0b" }}>
          {jobs.length} job{jobs.length > 1 ? "s" : ""} awaiting your WhatsApp approval
        </div>
        <div style={{ fontSize: 12, color: "#78563b", marginTop: 2 }}>
          {jobs.map(j => `${j.title} @ ${j.company}`).join(" · ")}
        </div>
      </div>
      <div style={{ fontSize: 12, color: "#78563b" }}>
        Reply YES / NO on WhatsApp
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────

export default function JobAgentDashboard() {
  const [jobs, setJobs] = useState(MOCK_JOBS);
  const [stats, setStats] = useState(MOCK_STATS);
  const [selectedJob, setSelectedJob] = useState(null);
  const [chatJob, setChatJob] = useState(null);
  const [filter, setFilter] = useState("all");
  const [scanRunning, setScanRunning] = useState(false);
  const [activeTab, setActiveTab] = useState("pipeline");

  const filteredJobs = filter === "all" ? jobs : jobs.filter(j => j.status === filter);

  const pendingApproval = jobs.filter(j => j.status === "pending_approval");

  const chartData = [
    { name: "Found", value: stats.discovered + stats.analyzed, color: "#64748b" },
    { name: "Pending", value: stats.pending_approval, color: "#f59e0b" },
    { name: "Applied", value: stats.applied, color: "#34d399" },
    { name: "Interview", value: stats.interviewing, color: "#38bdf8" },
    { name: "Offer", value: stats.offer, color: "#fbbf24" },
    { name: "Rejected", value: stats.rejected, color: "#f87171" },
  ];

  const startScan = async () => {
    setScanRunning(true);
    await new Promise(r => setTimeout(r, 3000));
    setScanRunning(false);
  };

  const tabs = ["pipeline", "analytics", "settings"];

  return (
    <div style={{
      minHeight: "100vh",
      background: "#050c12",
      color: "#c8d6e5",
      fontFamily: "'Inter', -apple-system, sans-serif",
      display: "flex",
      flexDirection: "column",
    }}>
      {/* ── Global Fonts ── */}
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700;800&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: #080e14; }
        ::-webkit-scrollbar-thumb { background: #1e2d3d; border-radius: 2px; }
        input::placeholder { color: #2a3d50; }
      `}</style>

      {/* ── Top Bar ── */}
      <div style={{
        padding: "0 24px",
        borderBottom: "1px solid #1e2d3d",
        display: "flex", alignItems: "center", gap: 24, height: 52,
        background: "#080e14",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 6,
            background: "linear-gradient(135deg, #2563eb, #7c3aed)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14,
          }}>🤖</div>
          <span style={{ fontWeight: 800, fontSize: 15, letterSpacing: "-0.02em" }}>JobAgent</span>
          <span style={{
            fontSize: 10, color: "#2563eb", background: "#2563eb15",
            border: "1px solid #2563eb33", borderRadius: 4,
            padding: "1px 6px", fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600,
          }}>v1.0</span>
        </div>

        <div style={{ display: "flex", gap: 2, marginLeft: 8 }}>
          {tabs.map(t => (
            <button key={t} onClick={() => setActiveTab(t)} style={{
              background: activeTab === t ? "#0f1923" : "transparent",
              border: activeTab === t ? "1px solid #1e2d3d" : "1px solid transparent",
              borderRadius: 6, padding: "5px 14px",
              color: activeTab === t ? "#c8d6e5" : "#4a6375",
              fontSize: 12, fontWeight: 500, cursor: "pointer",
              textTransform: "capitalize",
            }}>{t}</button>
          ))}
        </div>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          {/* Scan status indicator */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#4a6375" }}>
            <div style={{
              width: 7, height: 7, borderRadius: "50%",
              background: scanRunning ? "#34d399" : "#1e2d3d",
              boxShadow: scanRunning ? "0 0 6px #34d399" : "none",
              animation: scanRunning ? "pulse 1.5s ease-in-out infinite" : "none",
            }} />
            {scanRunning ? "Scanning…" : "Idle"}
          </div>
          <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>

          <button
            onClick={startScan}
            disabled={scanRunning}
            style={{
              background: scanRunning ? "#0f1923" : "linear-gradient(135deg, #2563eb, #1d4ed8)",
              border: `1px solid ${scanRunning ? "#1e2d3d" : "#3b82f655"}`,
              borderRadius: 7, padding: "7px 16px",
              color: scanRunning ? "#4a6375" : "#fff",
              fontSize: 12, fontWeight: 600, cursor: scanRunning ? "default" : "pointer",
              letterSpacing: "0.02em",
            }}
          >
            {scanRunning ? "⟳ Scanning…" : "▶ Run Scan"}
          </button>
        </div>
      </div>

      {/* ── Main Content ── */}
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>

        {activeTab === "pipeline" && (
          <>
            {/* Stats Row */}
            <div style={{
              padding: "16px 24px",
              borderBottom: "1px solid #1e2d3d",
              display: "flex", gap: 10, overflowX: "auto",
            }}>
              <StatCard label="Total" value={stats.total} color="#c8d6e5" />
              <StatCard label="Pending 📱" value={stats.pending_approval} color="#f59e0b" accent="#f59e0b" />
              <StatCard label="Applied" value={stats.applied} color="#34d399" accent="#34d399" />
              <StatCard label="Interviewing" value={stats.interviewing} color="#38bdf8" accent="#38bdf8" />
              <StatCard label="Offers 🎉" value={stats.offer} color="#fbbf24" accent="#fbbf24" />
              <StatCard label="Rejected" value={stats.rejected} color="#f87171" />
              <StatCard label="Skipped" value={stats.skipped} color="#475569" />
            </div>

            <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
              {/* Jobs Table */}
              <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
                {/* Filters + Banner */}
                <div style={{ padding: "12px 20px" }}>
                  <PendingApprovalBanner jobs={pendingApproval} />

                  {/* Filter Tabs */}
                  <div style={{ display: "flex", gap: 6 }}>
                    {["all", "pending_approval", "analyzed", "applied", "interviewing", "offer", "skipped"].map(f => (
                      <button key={f} onClick={() => setFilter(f)} style={{
                        background: filter === f ? "#0f1923" : "transparent",
                        border: `1px solid ${filter === f ? STATUS_META[f]?.color || "#2563eb" : "#1e2d3d"}`,
                        borderRadius: 6, padding: "4px 12px",
                        color: filter === f ? STATUS_META[f]?.color || "#c8d6e5" : "#4a6375",
                        fontSize: 11, cursor: "pointer", fontWeight: 500,
                        textTransform: "capitalize",
                      }}>
                        {f === "all" ? `All (${stats.total})` : (STATUS_META[f]?.label || f)}
                        {f !== "all" && stats[f] ? ` (${stats[f]})` : ""}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Table Header */}
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 140px 130px 80px 90px 80px",
                  gap: 12, padding: "8px 20px",
                  borderBottom: "1px solid #1e2d3d",
                  fontSize: 10, color: "#2a3d50", letterSpacing: "0.1em",
                  fontFamily: "'IBM Plex Mono', monospace",
                  textTransform: "uppercase",
                }}>
                  <span>Role / Company</span>
                  <span>Status</span>
                  <span>Found</span>
                  <span>Match</span>
                  <span>Type</span>
                  <span></span>
                </div>

                {/* Job Rows */}
                <div style={{ flex: 1 }}>
                  {filteredJobs.map(job => (
                    <JobRow
                      key={job.id}
                      job={job}
                      onSelect={setSelectedJob}
                      onChat={j => setChatJob(j)}
                      selected={selectedJob?.id === job.id}
                    />
                  ))}
                  {filteredJobs.length === 0 && (
                    <div style={{ padding: 40, textAlign: "center", color: "#2a3d50", fontSize: 13 }}>
                      No jobs in this category yet
                    </div>
                  )}
                </div>
              </div>

              {/* Job Detail Pane */}
              {selectedJob && (
                <div style={{
                  width: 320, borderLeft: "1px solid #1e2d3d",
                  background: "#080e14", overflowY: "auto", padding: 20,
                  flexShrink: 0,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "#c8d6e5", lineHeight: 1.3 }}>{selectedJob.title}</div>
                      <div style={{ fontSize: 12, color: "#4a6375", marginTop: 4 }}>{selectedJob.company}</div>
                      <div style={{ fontSize: 12, color: "#4a6375" }}>{selectedJob.location}</div>
                    </div>
                    <button onClick={() => setSelectedJob(null)} style={{ background: "none", border: "none", color: "#2a3d50", cursor: "pointer", fontSize: 16 }}>✕</button>
                  </div>

                  <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
                    <StatusBadge status={selectedJob.status} />
                    <ScorePill score={selectedJob.match_score} />
                  </div>

                  {selectedJob.ai_analysis?.highlights?.length > 0 && (
                    <div style={{ marginBottom: 14 }}>
                      <div style={{ fontSize: 10, color: "#2a3d50", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8, fontFamily: "'IBM Plex Mono', monospace" }}>Strengths</div>
                      {selectedJob.ai_analysis.highlights.map((h, i) => (
                        <div key={i} style={{ fontSize: 12, color: "#c8d6e5", marginBottom: 4, display: "flex", gap: 8 }}>
                          <span style={{ color: "#34d399" }}>✓</span>{h}
                        </div>
                      ))}
                    </div>
                  )}

                  {selectedJob.ai_analysis?.salary_estimate && (
                    <div style={{ marginBottom: 14 }}>
                      <div style={{ fontSize: 10, color: "#2a3d50", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6, fontFamily: "'IBM Plex Mono', monospace" }}>Salary Est.</div>
                      <div style={{ fontSize: 13, color: "#fbbf24", fontFamily: "'IBM Plex Mono', monospace" }}>{selectedJob.ai_analysis.salary_estimate}</div>
                    </div>
                  )}

                  <div style={{ display: "flex", gap: 8, flexDirection: "column" }}>
                    <button onClick={() => setChatJob(selectedJob)} style={{
                      background: "#0f1923", border: "1px solid #1e2d3d",
                      borderRadius: 7, padding: "9px 16px",
                      color: "#c8d6e5", fontSize: 12, fontWeight: 600, cursor: "pointer",
                    }}>💬 Chat About This Job</button>
                    <a href={selectedJob.url} target="_blank" rel="noopener noreferrer" style={{
                      display: "block", textAlign: "center",
                      background: "transparent", border: "1px solid #1e2d3d",
                      borderRadius: 7, padding: "8px 16px",
                      color: "#4a6375", fontSize: 12, textDecoration: "none",
                    }}>🔗 Open on LinkedIn</a>
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        {activeTab === "analytics" && (
          <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#c8d6e5" }}>Pipeline Analytics</div>
            <div style={{ background: "#0f1923", border: "1px solid #1e2d3d", borderRadius: 10, padding: 24, height: 280 }}>
              <div style={{ fontSize: 12, color: "#4a6375", marginBottom: 16, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "'IBM Plex Mono', monospace" }}>Jobs by Stage</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={chartData} barCategoryGap="30%">
                  <XAxis dataKey="name" tick={{ fill: "#4a6375", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#4a6375", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip
                    contentStyle={{ background: "#080e14", border: "1px solid #1e2d3d", borderRadius: 6, fontSize: 12 }}
                    labelStyle={{ color: "#c8d6e5" }}
                    itemStyle={{ color: "#c8d6e5" }}
                  />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div style={{ background: "#0f1923", border: "1px solid #1e2d3d", borderRadius: 10, padding: 20 }}>
                <div style={{ fontSize: 12, color: "#4a6375", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "'IBM Plex Mono', monospace" }}>Conversion Rate</div>
                <div style={{ fontSize: 36, fontWeight: 800, color: "#34d399", fontFamily: "'IBM Plex Mono', monospace" }}>
                  {stats.total > 0 ? Math.round((stats.applied / stats.total) * 100) : 0}%
                </div>
                <div style={{ fontSize: 12, color: "#4a6375", marginTop: 4 }}>of found jobs → applied</div>
              </div>
              <div style={{ background: "#0f1923", border: "1px solid #1e2d3d", borderRadius: 10, padding: 20 }}>
                <div style={{ fontSize: 12, color: "#4a6375", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "'IBM Plex Mono', monospace" }}>Interview Rate</div>
                <div style={{ fontSize: 36, fontWeight: 800, color: "#38bdf8", fontFamily: "'IBM Plex Mono', monospace" }}>
                  {stats.applied > 0 ? Math.round((stats.interviewing / stats.applied) * 100) : 0}%
                </div>
                <div style={{ fontSize: 12, color: "#4a6375", marginTop: 4 }}>of applied → interview</div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "settings" && (
          <div style={{ padding: 24, maxWidth: 600 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#c8d6e5", marginBottom: 20 }}>Configuration</div>
            {[
              { label: "Anthropic API Key", value: "sk-ant-••••••••••••••", type: "password" },
              { label: "LinkedIn Email", value: "you@email.com", type: "text" },
              { label: "Min Match Score", value: "70", type: "number" },
              { label: "WhatsApp Number", value: "+91 XXXXXXXXXX", type: "tel" },
              { label: "Max Applications / Day", value: "10", type: "number" },
            ].map(f => (
              <div key={f.label} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, color: "#4a6375", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "'IBM Plex Mono', monospace" }}>{f.label}</div>
                <input
                  type={f.type}
                  defaultValue={f.value}
                  style={{
                    width: "100%", background: "#0f1923", border: "1px solid #1e2d3d",
                    borderRadius: 7, padding: "10px 14px", color: "#c8d6e5",
                    fontSize: 13, fontFamily: "inherit", outline: "none",
                  }}
                />
              </div>
            ))}
            <div style={{ fontSize: 11, color: "#2a3d50", marginTop: 8 }}>
              Changes are saved to config/config.yaml. Restart the agent to apply.
            </div>
          </div>
        )}
      </div>

      {/* ── Chat Panel (Overlay) ── */}
      {chatJob && <ChatPanel job={chatJob} onClose={() => setChatJob(null)} />}
    </div>
  );
}
