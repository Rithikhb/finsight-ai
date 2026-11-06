import React, { useState, useEffect } from "react";
import {
  LayoutDashboard, UploadCloud, ListOrdered, PieChart as PieIcon, Repeat,
  AlertTriangle, Wallet, HeartPulse, FileSpreadsheet, ShieldCheck,
  MessageSquare, LogOut, Sparkles, CheckCircle2, XCircle, Filter, Download, Trash2
} from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
  PieChart, Pie, Cell, LineChart, Line, CartesianGrid, AreaChart, Area
} from "recharts";

const API_BASE = "http://127.0.0.1:8000/api";
const CHART_COLORS = ["#0D9488", "#0284C7", "#6366F1", "#F59E0B", "#EC4899", "#10B981", "#8B5CF6", "#64748B"];

const CATEGORIES = [
  "Food and Dining", "Groceries", "Transportation", "Shopping", "Housing and Rent",
  "Utilities", "Healthcare", "Education", "Entertainment", "Travel", "Insurance",
  "EMI and Loan Payments", "Bank Charges", "Investments and Transfers",
  "Salary and Income", "Freelance or Business Income", "Refunds and Reimbursements", "Other"
];

export default function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem("finsight_token"));
  const [user, setUser] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<string>("overview");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authForm, setAuthForm] = useState({ name: "", email: "", password: "", currency: "INR" });
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [statusBanner, setStatusBanner] = useState<string | null>(null);

  // Filters & Core Data
  const [accounts, setAccounts] = useState<any[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>("");
  const [selectedMonth, setSelectedMonth] = useState<string>("");
  const [overview, setOverview] = useState<any>(null);
  const [transactions, setTransactions] = useState<any[]>([]);
  const [recurring, setRecurring] = useState<any[]>([]);
  const [anomalies, setAnomalies] = useState<any[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [budgets, setBudgets] = useState<any>(null);
  const [statements, setStatements] = useState<any[]>([]);

  // Upload Preview State
  const [uploadPreview, setUploadPreview] = useState<any>(null);
  const [uploadAccountId, setUploadAccountId] = useState<number>(0);
  const [isUploading, setIsUploading] = useState<boolean>(false);

  // Drill-down category modal
  const [drillCategory, setDrillCategory] = useState<string | null>(null);

  // Budget Form & Simulator
  const [newBudgetCat, setNewBudgetCat] = useState<string>("Food and Dining");
  const [newBudgetAmt, setNewBudgetAmt] = useState<string>("3500");
  const [simCutPct, setSimCutPct] = useState<number>(15);

  // AI Assistant State
  const [chatOpen, setChatOpen] = useState<boolean>(false);
  const [chatQuestion, setChatQuestion] = useState<string>("");
  const [chatHistory, setChatHistory] = useState<any[]>([]);

  const authHeaders = () => ({
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json"
  });

  const fetchAllData = async () => {
    if (!token) return;
    try {
      const [meRes, accRes, stmtRes] = await Promise.all([
        fetch(`${API_BASE}/auth/me`, { headers: authHeaders() }),
        fetch(`${API_BASE}/accounts`, { headers: authHeaders() }),
        fetch(`${API_BASE}/statements`, { headers: authHeaders() })
      ]);
      if (meRes.status === 401) {
        handleLogout();
        return;
      }
      const meData = await meRes.json();
      const accData = await accRes.json();
      setUser(meData);
      setAccounts(accData);
      if (accData.length > 0 && !uploadAccountId) setUploadAccountId(accData[0].id);
      setStatements(await stmtRes.json());

      const qParams = new URLSearchParams();
      if (selectedAccount) qParams.set("account_id", selectedAccount);
      if (selectedMonth) qParams.set("month", selectedMonth);

      const [ovRes, txnRes, recRes, anomRes, hlthRes, bdgRes] = await Promise.all([
        fetch(`${API_BASE}/analytics/overview?${qParams.toString()}`, { headers: authHeaders() }),
        fetch(`${API_BASE}/transactions?${qParams.toString()}`, { headers: authHeaders() }),
        fetch(`${API_BASE}/recurring`, { headers: authHeaders() }),
        fetch(`${API_BASE}/anomalies`, { headers: authHeaders() }),
        fetch(`${API_BASE}/financial-health`, { headers: authHeaders() }),
        fetch(`${API_BASE}/budgets${selectedMonth ? `?month=${selectedMonth}` : ""}`, { headers: authHeaders() })
      ]);

      setOverview(await ovRes.json());
      setTransactions(await txnRes.json());
      setRecurring(await recRes.json());
      setAnomalies(await anomRes.json());
      setHealth(await hlthRes.json());
      setBudgets(await bdgRes.json());
    } catch (err: any) {
      setErrorMsg("Failed to synchronize data with backend.");
    }
  };

  useEffect(() => {
    fetchAllData();
  }, [token, selectedAccount, selectedMonth]);

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    const endpoint = authMode === "login" ? "/auth/login" : "/auth/register";
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(authForm)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Authentication failed");
      localStorage.setItem("finsight_token", data.access_token);
      setToken(data.access_token);
      setUser(data.user);
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("finsight_token");
    setToken(null);
    setUser(null);
  };

  const handleLoadDemo = async () => {
    setStatusBanner("Loading 3-month synthetic demonstration dataset...");
    const res = await fetch(`${API_BASE}/demo/load`, { method: "POST", headers: authHeaders() });
    if (res.ok) {
      await fetchAllData();
      setStatusBanner("Synthetic Demo Loaded! All demo records are clearly labeled [SYNTHETIC DEMO].");
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setErrorMsg(null);
    const formData = new FormData();
    formData.append("file", file);
    formData.append("account_id", String(uploadAccountId || accounts[0]?.id));
    try {
      const res = await fetch(`${API_BASE}/statements/upload-preview`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      setUploadPreview(data);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setIsUploading(false);
    }
  };

  const handleConfirmImport = async () => {
    if (!uploadPreview) return;
    try {
      const res = await fetch(`${API_BASE}/statements/confirm-import`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(uploadPreview)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Import failed");
      setUploadPreview(null);
      setStatusBanner(`Successfully imported ${data.imported_count} verified transactions.`);
      await fetchAllData();
      setActiveTab("overview");
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const handleUpdateTransaction = async (txnId: number, updates: any) => {
    await fetch(`${API_BASE}/transactions/${txnId}`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify(updates)
    });
    await fetchAllData();
  };

  const handleAskAssistant = async (qText?: string) => {
    const query = qText || chatQuestion;
    if (!query.trim()) return;
    setChatQuestion("");
    setChatHistory((prev) => [...prev, { role: "user", text: query }]);
    const res = await fetch(`${API_BASE}/assistant/query`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ question: query, use_local_llm: false })
    });
    const data = await res.json();
    setChatHistory((prev) => [
      ...prev,
      { role: "assistant", text: data.answer, facts: data.grounding_facts, engine: data.engine_used }
    ]);
  };

  const handleExportReport = async (fmt: "csv" | "xlsx" | "pdf") => {
    const res = await fetch(
      `${API_BASE}/reports/export?format=${fmt}${selectedMonth ? `&month=${selectedMonth}` : ""}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `finsight_report.${fmt}`;
    a.click();
  };

  // ==================== AUTH SCREEN ====================
  if (!token) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4 text-slate-900">
        <div className="max-w-md w-full bg-white rounded-2xl shadow-lg border border-slate-200 p-8">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2.5 bg-teal-600 text-white rounded-xl">
              <ShieldCheck className="w-7 h-7" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">FinSight AI</h1>
              <p className="text-xs text-slate-500">Bank Statement Intelligence & Health Analyzer</p>
            </div>
          </div>

          {errorMsg && (
            <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
              {errorMsg}
            </div>
          )}

          <form onSubmit={handleAuthSubmit} className="space-y-4">
            {authMode === "register" && (
              <div>
                <label className="block text-xs font-semibold uppercase text-slate-600 mb-1">Full Name</label>
                <input
                  type="text"
                  required
                  value={authForm.name}
                  onChange={(e) => setAuthForm({ ...authForm, name: e.target.value })}
                  className="w-full px-3.5 py-2 border border-slate-300 rounded-lg text-sm"
                  placeholder="Rithik H B"
                />
              </div>
            )}
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-600 mb-1">Email Address</label>
              <input
                type="email"
                required
                value={authForm.email}
                onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })}
                className="w-full px-3.5 py-2 border border-slate-300 rounded-lg text-sm"
                placeholder="you@domain.com"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase text-slate-600 mb-1">Password (min 8 chars)</label>
              <input
                type="password"
                required
                minLength={8}
                value={authForm.password}
                onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })}
                className="w-full px-3.5 py-2 border border-slate-300 rounded-lg text-sm"
              />
            </div>
            <button
              type="submit"
              className="w-full py-2.5 bg-teal-600 hover:bg-teal-700 text-white font-semibold rounded-lg text-sm transition"
            >
              {authMode === "login" ? "Sign In Securely" : "Create Account"}
            </button>
          </form>

          <div className="mt-5 text-center text-sm text-slate-600">
            {authMode === "login" ? "New to FinSight AI?" : "Already registered?"}{" "}
            <button
              onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
              className="text-teal-600 font-semibold hover:underline"
            >
              {authMode === "login" ? "Create an account" : "Sign in"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  const cards = overview?.summary_cards || {};
  const cur = user?.currency || "INR";

  // ==================== MAIN AUTHENTICATED SHELL ====================
  return (
    <div className="min-h-screen bg-slate-50 flex text-slate-900">
      {/* Sidebar */}
      <aside className="w-64 bg-white border-r border-slate-200 flex flex-col justify-between shrink-0">
        <div>
          <div className="p-5 border-b border-slate-100 flex items-center gap-3">
            <div className="p-2 bg-teal-600 text-white rounded-lg">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <span className="font-bold text-lg text-slate-900">FinSight AI</span>
              <span className="block text-[11px] text-slate-500">Privacy-First Intelligence</span>
            </div>
          </div>

          <nav className="p-3 space-y-1">
            {[
              { id: "overview", label: "Overview", icon: LayoutDashboard },
              { id: "upload", label: "Upload Statements", icon: UploadCloud },
              { id: "transactions", label: "Transactions", icon: ListOrdered },
              { id: "analytics", label: "Spending Analytics", icon: PieIcon },
              { id: "recurring", label: "Recurring Payments", icon: Repeat },
              { id: "anomalies", label: "Unusual Activity", icon: AlertTriangle, badge: cards.unusual_pending_count },
              { id: "budgets", label: "Budget Planner", icon: Wallet },
              { id: "health", label: "Financial Health", icon: HeartPulse },
              { id: "reports", label: "Reports", icon: FileSpreadsheet },
              { id: "settings", label: "Settings & Privacy", icon: ShieldCheck }
            ].map((item) => {
              const Icon = item.icon;
              const active = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-lg text-sm font-medium transition ${
                    active ? "bg-teal-50 text-teal-700 font-semibold" : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  <span className="flex items-center gap-3">
                    <Icon className="w-4 h-4" />
                    {item.label}
                  </span>
                  {item.badge ? (
                    <span className="px-2 py-0.5 text-xs rounded-full bg-amber-100 text-amber-800 font-bold">
                      {item.badge}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="p-4 border-t border-slate-200 space-y-2">
          <button
            onClick={handleLoadDemo}
            className="w-full py-2 px-3 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5"
          >
            <Sparkles className="w-4 h-4" /> Load Synthetic Demo
          </button>
          <button
            onClick={handleLogout}
            className="w-full py-2 px-3 text-slate-600 hover:bg-slate-100 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5"
          >
            <LogOut className="w-4 h-4" /> Sign Out ({user?.name})
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Navigation Bar */}
        <header className="bg-white border-b border-slate-200 px-6 py-3.5 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Filter className="w-4 h-4 text-slate-400" />
            <select
              value={selectedAccount}
              onChange={(e) => setSelectedAccount(e.target.value)}
              className="border border-slate-300 rounded-lg px-3 py-1.5 text-xs font-medium bg-white"
            >
              <option value="">All Accounts</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.display_name} ({a.account_type})
                </option>
              ))}
            </select>

            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              className="border border-slate-300 rounded-lg px-3 py-1.5 text-xs font-medium bg-white"
            >
              <option value="">All Available Months</option>
              {overview?.available_months?.map((m: string) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setChatOpen(!chatOpen)}
              className="px-3.5 py-1.5 bg-teal-600 hover:bg-teal-700 text-white rounded-lg text-xs font-semibold flex items-center gap-2 shadow-sm"
            >
              <MessageSquare className="w-4 h-4" /> Ask FinSight AI Assistant
            </button>
          </div>
        </header>

        {statusBanner && (
          <div className="mx-6 mt-4 p-3 bg-teal-50 border border-teal-200 text-teal-800 rounded-lg text-xs flex justify-between items-center">
            <span>{statusBanner}</span>
            <button onClick={() => setStatusBanner(null)} className="font-bold">✕</button>
          </div>
        )}
        {errorMsg && (
          <div className="mx-6 mt-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-xs flex justify-between items-center">
            <span>{errorMsg}</span>
            <button onClick={() => setErrorMsg(null)} className="font-bold">✕</button>
          </div>
        )}

        <main className="p-6 space-y-6 overflow-y-auto flex-1">
          {/* Empty State if no transactions */}
          {transactions.length === 0 && activeTab !== "upload" && (
            <div className="bg-white rounded-2xl border border-slate-200 p-10 text-center max-w-xl mx-auto my-8">
              <UploadCloud className="w-12 h-12 text-teal-600 mx-auto mb-3" />
              <h2 className="text-lg font-bold text-slate-900">No Transactions Imported Yet</h2>
              <p className="text-sm text-slate-600 mt-1 mb-6">
                Upload a CSV, Excel, or text-based PDF bank statement to extract and verify your records, or explore the complete workflow immediately with synthetic sample data.
              </p>
              <div className="flex justify-center gap-3">
                <button
                  onClick={() => setActiveTab("upload")}
                  className="px-4 py-2 bg-teal-600 text-white rounded-lg text-sm font-semibold"
                >
                  Upload Statement
                </button>
                <button
                  onClick={handleLoadDemo}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-semibold"
                >
                  Load 3-Month Synthetic Demo
                </button>
              </div>
            </div>
          )}

          {/* 1. OVERVIEW TAB */}
          {activeTab === "overview" && transactions.length > 0 && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {[
                  { label: "Total Verified Income", val: `${cur} ${cards.total_income?.toLocaleString()}`, color: "text-emerald-600", sub: "Excludes self-transfers" },
                  { label: "Total Net Expenses", val: `${cur} ${cards.total_expenses?.toLocaleString()}`, color: "text-slate-900", sub: `Net of ${cur} ${cards.total_refunds || 0} refunds` },
                  { label: "Net Cash Flow", val: `${cur} ${cards.net_cash_flow?.toLocaleString()}`, color: cards.net_cash_flow >= 0 ? "text-emerald-600" : "text-red-600", sub: "Observed period net" },
                  { label: "Savings Rate", val: `${cards.savings_rate}%`, color: cards.savings_rate >= 20 ? "text-emerald-600" : "text-amber-600", sub: "(Income - Expense) / Income" },
                  { label: "Avg Daily Spending", val: `${cur} ${cards.avg_daily_spending?.toLocaleString()}`, color: "text-slate-800", sub: "Across active period" },
                  { label: "Recurring Monthly Est.", val: `${cur} ${cards.recurring_monthly_payments?.toLocaleString()}`, color: "text-indigo-600", sub: `${recurring.length} subscriptions/EMIs` },
                  { label: "Processed Transactions", val: cards.transaction_count, color: "text-slate-900", sub: `Transfers excluded: ${cur} ${cards.total_transfers_excluded}` },
                  { label: "Unusual Activity Review", val: cards.unusual_pending_count, color: cards.unusual_pending_count > 0 ? "text-amber-600" : "text-emerald-600", sub: "Flagged for user review" }
                ].map((c, idx) => (
                  <div key={idx} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
                    <span className="text-xs font-medium text-slate-500">{c.label}</span>
                    <div className={`text-xl font-bold mt-1 ${c.color}`}>{c.val}</div>
                    <span className="text-[11px] text-slate-400">{c.sub}</span>
                  </div>
                ))}
              </div>

              {/* Charts Row 1 */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-sm font-bold text-slate-800 mb-4">Monthly Income vs. Expenses & Net Cash Flow</h3>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={overview.monthly_trends}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                        <XAxis dataKey="month" fontSize={12} />
                        <YAxis fontSize={12} />
                        <Tooltip />
                        <Legend />
                        <Bar dataKey="income" name="Income" fill="#10B981" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="expenses" name="Net Expenses" fill="#0D9488" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="net_cash_flow" name="Net Cash Flow" fill="#6366F1" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="text-sm font-bold text-slate-800">Spending Distribution (Click slice to drill down)</h3>
                    {drillCategory && (
                      <button onClick={() => setDrillCategory(null)} className="text-xs text-teal-600 underline">
                        Clear filter ({drillCategory})
                      </button>
                    )}
                  </div>
                  <div className="h-64 flex items-center">
                    <ResponsiveContainer width="60%" height="100%">
                      <PieChart>
                        <Pie
                          data={overview.category_distribution}
                          dataKey="amount"
                          nameKey="category"
                          innerRadius={50}
                          outerRadius={85}
                          onClick={(entry) => setDrillCategory(entry.category)}
                          className="cursor-pointer"
                        >
                          {overview.category_distribution.map((_: any, i: number) => (
                            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="w-40 space-y-1.5 text-xs overflow-y-auto max-h-60">
                      {overview.category_distribution.map((c: any, i: number) => (
                        <button
                          key={c.category}
                          onClick={() => setDrillCategory(c.category)}
                          className="w-full flex justify-between items-center text-left hover:bg-slate-50 p-1 rounded"
                        >
                          <span className="truncate flex items-center gap-1.5">
                            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                            {c.category}
                          </span>
                          <span className="font-semibold">{c.percentage}%</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Drill-down table when a category slice is clicked */}
              {drillCategory && (
                <div className="bg-teal-50/60 border border-teal-200 rounded-xl p-4">
                  <div className="flex justify-between items-center mb-2">
                    <h4 className="text-sm font-bold text-teal-900">
                      Drill-Down Transactions: {drillCategory}
                    </h4>
                    <button onClick={() => setDrillCategory(null)} className="text-xs text-teal-700 font-bold">
                      Close ✕
                    </button>
                  </div>
                  <div className="overflow-x-auto bg-white rounded-lg border border-slate-200">
                    <table className="w-full text-xs text-left">
                      <thead className="bg-slate-100 text-slate-600 uppercase">
                        <tr>
                          <th className="p-2.5">Date</th>
                          <th className="p-2.5">Merchant</th>
                          <th className="p-2.5">Description</th>
                          <th className="p-2.5 text-right">Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {transactions
                          .filter((t) => t.category === drillCategory)
                          .map((t) => (
                            <tr key={t.id} className="border-t border-slate-100">
                              <td className="p-2.5">{t.txn_date}</td>
                              <td className="p-2.5 font-semibold">{t.merchant}</td>
                              <td className="p-2.5 text-slate-500">{t.description}</td>
                              <td className="p-2.5 text-right font-bold">{cur} {Math.abs(t.signed_amount).toLocaleString()}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Daily Spending Activity Line Chart */}
              <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <h3 className="text-sm font-bold text-slate-800 mb-4">Daily Spending Activity & High-Spend Spikes</h3>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={overview.daily_spending}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                      <XAxis dataKey="date" fontSize={11} />
                      <YAxis fontSize={11} />
                      <Tooltip />
                      <Area type="monotone" dataKey="amount" stroke="#0284C7" fill="#BAE6FD" name="Daily Spend" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </>
          )}

          {/* 2. UPLOAD STATEMENTS TAB */}
          {activeTab === "upload" && (
            <div className="space-y-6">
              <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                <h2 className="text-base font-bold text-slate-900">Upload & Reconcile Bank Statement</h2>
                <p className="text-xs text-slate-500 mt-1">
                  Supported formats: <b>CSV, Excel (.xlsx/.xls), and text-based PDF bank statements</b> (Max {10}MB).
                  All values are validated and mathematically reconciled before import.
                </p>

                <div className="mt-4 flex flex-wrap items-center gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Target Account</label>
                    <select
                      value={uploadAccountId}
                      onChange={(e) => setUploadAccountId(Number(e.target.value))}
                      className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                    >
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>{a.display_name}</option>
                      ))}
                    </select>
                  </div>

                  <div className="flex-1">
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Select Statement File</label>
                    <input
                      type="file"
                      accept=".csv,.xlsx,.xls,.pdf"
                      onChange={handleFileUpload}
                      disabled={isUploading}
                      className="block w-full text-sm text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-teal-50 file:text-teal-700 hover:file:bg-teal-100"
                    />
                  </div>
                </div>
              </div>

              {/* Interactive Preview & Validation Screen */}
              {uploadPreview && (
                <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
                  <div className="flex flex-wrap justify-between items-center gap-4">
                    <div>
                      <h3 className="text-sm font-bold text-slate-900">
                        Extraction Preview: {uploadPreview.filename}
                      </h3>
                      <p className="text-xs text-slate-500">
                        Discovered: {uploadPreview.total_rows_discovered} | Valid: {uploadPreview.valid_rows_count} | Needs Correction: {uploadPreview.rows_requiring_correction} | Duplicate Candidates: {uploadPreview.duplicate_candidates_count}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setUploadPreview(null)}
                        className="px-3.5 py-2 border border-slate-300 rounded-lg text-xs font-semibold text-slate-600"
                      >
                        Discard Upload
                      </button>
                      <button
                        onClick={handleConfirmImport}
                        className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg text-xs font-semibold"
                      >
                        Confirm & Import Selected Rows
                      </button>
                    </div>
                  </div>

                  <div className={`p-3 rounded-lg text-xs border ${
                    uploadPreview.reconciliation_status === "VERIFIED"
                      ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                      : uploadPreview.reconciliation_status === "DISCREPANCY_DETECTED"
                      ? "bg-red-50 border-red-200 text-red-800"
                      : "bg-amber-50 border-amber-200 text-amber-800"
                  }`}>
                    <b>Ledger Reconciliation Status ({uploadPreview.reconciliation_status}):</b> {uploadPreview.reconciliation_details}
                  </div>

                  <div className="overflow-x-auto max-h-96 border border-slate-200 rounded-lg">
                    <table className="w-full text-xs text-left">
                      <thead className="bg-slate-100 text-slate-600 sticky top-0">
                        <tr>
                          <th className="p-2">Import?</th>
                          <th className="p-2">Date</th>
                          <th className="p-2">Description</th>
                          <th className="p-2">Debit</th>
                          <th className="p-2">Credit</th>
                          <th className="p-2">Balance</th>
                          <th className="p-2">Auto Category (Conf.)</th>
                          <th className="p-2">Validation / Duplicate Notes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {uploadPreview.rows.map((r: any, idx: number) => (
                          <tr key={r.temp_id} className={`border-t ${r.validation_errors.length ? "bg-red-50/40" : r.is_duplicate_candidate ? "bg-amber-50/40" : ""}`}>
                            <td className="p-2">
                              <input
                                type="checkbox"
                                checked={r.include_in_import}
                                onChange={(e) => {
                                  const updated = [...uploadPreview.rows];
                                  updated[idx].include_in_import = e.target.checked;
                                  setUploadPreview({ ...uploadPreview, rows: updated });
                                }}
                              />
                            </td>
                            <td className="p-2">
                              <input
                                type="text"
                                value={r.txn_date || r.raw_date}
                                onChange={(e) => {
                                  const updated = [...uploadPreview.rows];
                                  updated[idx].txn_date = e.target.value;
                                  setUploadPreview({ ...uploadPreview, rows: updated });
                                }}
                                className="border border-slate-300 rounded px-1.5 py-0.5 w-24 text-xs"
                              />
                            </td>
                            <td className="p-2">
                              <input
                                type="text"
                                value={r.description}
                                onChange={(e) => {
                                  const updated = [...uploadPreview.rows];
                                  updated[idx].description = e.target.value;
                                  setUploadPreview({ ...uploadPreview, rows: updated });
                                }}
                                className="border border-slate-300 rounded px-1.5 py-0.5 w-48 text-xs"
                              />
                            </td>
                            <td className="p-2 font-mono">{r.debit.toFixed(2)}</td>
                            <td className="p-2 font-mono">{r.credit.toFixed(2)}</td>
                            <td className="p-2 font-mono">{r.balance !== null ? r.balance.toFixed(2) : "-"}</td>
                            <td className="p-2">
                              <select
                                value={r.category}
                                onChange={(e) => {
                                  const updated = [...uploadPreview.rows];
                                  updated[idx].category = e.target.value;
                                  setUploadPreview({ ...uploadPreview, rows: updated });
                                }}
                                className="border border-slate-300 rounded px-1.5 py-0.5 text-xs"
                              >
                                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                              </select>
                              <span className="ml-1 text-[10px] text-slate-400">({Math.round(r.categorization_confidence * 100)}%)</span>
                            </td>
                            <td className="p-2 text-[11px]">
                              {r.validation_errors.map((err: string, i: number) => (
                                <span key={i} className="block text-red-600 font-semibold">{err}</span>
                              ))}
                              {r.is_duplicate_candidate && (
                                <span className="block text-amber-700 font-medium">{r.duplicate_reason}</span>
                              )}
                              {!r.validation_errors.length && !r.is_duplicate_candidate && (
                                <span className="text-emerald-600">Verified OK</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Imported Statements History */}
              <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                <h3 className="text-sm font-bold text-slate-900 mb-3">Uploaded Statement History</h3>
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-100 text-slate-600">
                    <tr>
                      <th className="p-2.5">Filename</th>
                      <th className="p-2.5">Date Range</th>
                      <th className="p-2.5">Transactions</th>
                      <th className="p-2.5">Reconciliation</th>
                      <th className="p-2.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {statements.map((s) => (
                      <tr key={s.id} className="border-t border-slate-100">
                        <td className="p-2.5 font-semibold">
                          {s.original_filename} {s.is_synthetic && <span className="ml-1 px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded text-[10px]">SYNTHETIC</span>}
                        </td>
                        <td className="p-2.5">{s.period_start} to {s.period_end}</td>
                        <td className="p-2.5">{s.imported_count}</td>
                        <td className="p-2.5">{s.reconciliation_status}</td>
                        <td className="p-2.5 text-right">
                          <button
                            onClick={async () => {
                              await fetch(`${API_BASE}/statements/${s.id}`, { method: "DELETE", headers: authHeaders() });
                              await fetchAllData();
                            }}
                            className="text-red-600 hover:underline font-semibold"
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 3. TRANSACTIONS TAB */}
          {activeTab === "transactions" && (
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <div className="flex justify-between items-center mb-4">
                <div>
                  <h2 className="text-base font-bold text-slate-900">Transactions & Rule Classification Editor</h2>
                  <p className="text-xs text-slate-500">
                    Edit any category to automatically train FinSight AI on that merchant for future statements.
                  </p>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-100 text-slate-600 uppercase">
                    <tr>
                      <th className="p-2.5">Date</th>
                      <th className="p-2.5">Merchant & Description</th>
                      <th className="p-2.5">Category & Rule</th>
                      <th className="p-2.5">Type</th>
                      <th className="p-2.5">Confidence</th>
                      <th className="p-2.5 text-right">Signed Amount</th>
                      <th className="p-2.5 text-right">Running Bal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((t) => (
                      <tr key={t.id} className={`border-t border-slate-100 ${t.is_unusual ? "bg-amber-50/40" : ""}`}>
                        <td className="p-2.5 whitespace-nowrap">{t.txn_date}</td>
                        <td className="p-2.5">
                          <div className="font-semibold text-slate-900">{t.merchant}</div>
                          <div className="text-[11px] text-slate-400 truncate max-w-xs">{t.description}</div>
                        </td>
                        <td className="p-2.5">
                          <select
                            value={t.category}
                            onChange={(e) =>
                              handleUpdateTransaction(t.id, { category: e.target.value, apply_rule_to_similar: true })
                            }
                            className="border border-slate-300 rounded px-2 py-1 text-xs bg-white"
                          >
                            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                          </select>
                        </td>
                        <td className="p-2.5">
                          <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-medium text-[10px]">
                            {t.txn_type}
                          </span>
                        </td>
                        <td className="p-2.5 text-[11px] text-slate-500">
                          {Math.round(t.categorization_confidence * 100)}% ({t.classification_source})
                        </td>
                        <td className={`p-2.5 text-right font-bold ${t.signed_amount >= 0 ? "text-emerald-600" : "text-slate-900"}`}>
                          {t.signed_amount >= 0 ? "+" : ""}{cur} {t.signed_amount.toLocaleString()}
                        </td>
                        <td className="p-2.5 text-right font-mono text-slate-500">
                          {t.balance !== null ? `${cur} ${t.balance.toLocaleString()}` : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 4. SPENDING ANALYTICS TAB */}
          {activeTab === "analytics" && overview && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-sm font-bold text-slate-800 mb-3">Essential vs. Discretionary Split</h3>
                  <div className="space-y-3 text-sm">
                    <div className="flex justify-between">
                      <span>Essential (Rent, Groceries, Utilities, EMIs, Health):</span>
                      <span className="font-bold text-teal-700">{cur} {overview.essential_vs_discretionary.essential.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Discretionary (Dining, Shopping, Entertainment, Travel):</span>
                      <span className="font-bold text-indigo-600">{cur} {overview.essential_vs_discretionary.discretionary.toLocaleString()}</span>
                    </div>
                  </div>
                </div>

                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                  <h3 className="text-sm font-bold text-slate-800 mb-3">Weekday vs. Weekend Spending</h3>
                  <div className="space-y-3 text-sm">
                    <div className="flex justify-between">
                      <span>Weekday Spending (Mon–Fri):</span>
                      <span className="font-bold text-slate-800">{cur} {overview.weekday_vs_weekend.weekday.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Weekend Spending (Sat–Sun):</span>
                      <span className="font-bold text-amber-600">{cur} {overview.weekday_vs_weekend.weekend.toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <h3 className="text-sm font-bold text-slate-800 mb-4">Top Spending Merchants</h3>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={overview.top_merchants} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" fontSize={12} />
                      <YAxis dataKey="merchant" type="category" width={140} fontSize={11} />
                      <Tooltip />
                      <Bar dataKey="amount" fill="#0D9488" radius={[0, 4, 4, 0]} name="Total Spend" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          )}

          {/* 5. RECURRING PAYMENTS TAB */}
          {activeTab === "recurring" && (
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
              <div>
                <h2 className="text-base font-bold text-slate-900">Recurring Subscriptions, Bills & EMIs</h2>
                <p className="text-xs text-slate-500">
                  Next payment windows and monthly equivalents are statistical estimates based on observed intervals (minimum 2 occurrences required).
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-100 text-slate-600 uppercase">
                    <tr>
                      <th className="p-2.5">Merchant</th>
                      <th className="p-2.5">Category</th>
                      <th className="p-2.5">Frequency</th>
                      <th className="p-2.5">Typical Amount</th>
                      <th className="p-2.5">Monthly Equivalent</th>
                      <th className="p-2.5">Next Expected Window</th>
                      <th className="p-2.5">Price Change Alert</th>
                      <th className="p-2.5">User Classification</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recurring.map((r) => (
                      <tr key={r.id} className="border-t border-slate-100">
                        <td className="p-2.5 font-bold">{r.merchant} ({r.occurrences}x)</td>
                        <td className="p-2.5">{r.category}</td>
                        <td className="p-2.5">{r.frequency}</td>
                        <td className="p-2.5 font-semibold">{cur} {r.typical_amount.toLocaleString()}</td>
                        <td className="p-2.5 text-teal-700 font-bold">{cur} {r.monthly_equivalent.toLocaleString()}/mo</td>
                        <td className="p-2.5">{r.next_expected_date} ({Math.round(r.confidence * 100)}% conf)</td>
                        <td className="p-2.5">
                          {r.has_price_increase ? (
                            <span className="px-2 py-0.5 bg-amber-100 text-amber-800 rounded font-semibold block">
                              {r.price_change_note}
                            </span>
                          ) : (
                            <span className="text-emerald-600">Stable</span>
                          )}
                        </td>
                        <td className="p-2.5">
                          <select
                            value={r.review_status}
                            onChange={async (e) => {
                              await fetch(`${API_BASE}/recurring/${r.id}`, {
                                method: "PATCH",
                                headers: authHeaders(),
                                body: JSON.stringify({ review_status: e.target.value })
                              });
                              await fetchAllData();
                            }}
                            className="border border-slate-300 rounded px-2 py-1 text-xs"
                          >
                            <option value="UNREVIEWED">Unreviewed</option>
                            <option value="USEFUL">Confirmed Useful</option>
                            <option value="UNWANTED">Flag to Cancel</option>
                            <option value="INCORRECT">Not Recurring</option>
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 6. UNUSUAL ACTIVITY TAB */}
          {activeTab === "anomalies" && (
            <div className="space-y-4">
              <div className="bg-amber-50 border border-amber-200 p-4 rounded-xl text-xs text-amber-900">
                <b>Explainable Review Policy:</b> Alerts below represent statistical deviations from your historical spending patterns (via Robust MAD Ratio, Velocity Checks, and Isolation Forest). They are <b>recommendations for review</b>, never automated declarations of fraud.
              </div>
              {anomalies.map((a) => (
                <div key={a.id} className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-wrap justify-between items-center gap-4">
                  <div className="space-y-1 max-w-2xl">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 text-[10px] font-bold rounded ${a.severity === "HIGH" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-800"}`}>
                        {a.severity} DEVIATION ({a.detection_method})
                      </span>
                      <span className="text-sm font-bold text-slate-900">
                        {a.merchant} — {cur} {a.amount.toLocaleString()} on {a.txn_date}
                      </span>
                    </div>
                    <p className="text-xs text-slate-600">{a.explanation}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {["EXPECTED", "REVIEWED", "INVESTIGATE", "DISMISSED"].map((st) => (
                      <button
                        key={st}
                        onClick={async () => {
                          await fetch(`${API_BASE}/anomalies/${a.id}`, {
                            method: "PATCH",
                            headers: authHeaders(),
                            body: JSON.stringify({ review_status: st })
                          });
                          await fetchAllData();
                        }}
                        className={`px-3 py-1.5 rounded-lg text-xs font-semibold border ${
                          a.review_status === st ? "bg-teal-600 text-white border-teal-600" : "bg-white text-slate-700 border-slate-300"
                        }`}
                      >
                        {st}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 7. BUDGET PLANNER TAB */}
          {activeTab === "budgets" && budgets && (
            <div className="space-y-6">
              <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                <h2 className="text-base font-bold text-slate-900 mb-1">Interactive Category Budget Planner ({budgets.month})</h2>
                <p className="text-xs text-slate-500 mb-4">{budgets.accounting_policy}</p>

                <div className="flex flex-wrap gap-3 items-end mb-6 bg-slate-50 p-4 rounded-lg border border-slate-200">
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Category</label>
                    <select
                      value={newBudgetCat}
                      onChange={(e) => setNewBudgetCat(e.target.value)}
                      className="border border-slate-300 rounded-lg px-3 py-1.5 text-xs bg-white"
                    >
                      {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1">Monthly Target ({cur})</label>
                    <input
                      type="number"
                      min="0"
                      value={newBudgetAmt}
                      onChange={(e) => setNewBudgetAmt(e.target.value)}
                      className="border border-slate-300 rounded-lg px-3 py-1.5 text-xs w-36"
                    />
                  </div>
                  <button
                    onClick={async () => {
                      await fetch(`${API_BASE}/budgets`, {
                        method: "POST",
                        headers: authHeaders(),
                        body: JSON.stringify({ category: newBudgetCat, target_amount: Number(newBudgetAmt), alert_threshold_pct: 85 })
                      });
                      await fetchAllData();
                    }}
                    className="px-4 py-1.5 bg-teal-600 text-white rounded-lg text-xs font-semibold"
                  >
                    Save Category Target
                  </button>
                </div>

                <div className="space-y-4">
                  {budgets.category_budgets.map((b: any) => (
                    <div key={b.id} className="p-4 border border-slate-200 rounded-lg">
                      <div className="flex justify-between text-xs font-semibold mb-1.5">
                        <span>{b.category} ({b.status})</span>
                        <span>
                          Actual: {cur} {b.actual_spending.toLocaleString()} / Target: {cur} {b.target_amount.toLocaleString()} ({b.utilization_pct ?? 0}%)
                        </span>
                      </div>
                      <div className="w-full h-2.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full ${b.utilization_pct > 100 ? "bg-red-500" : b.utilization_pct >= 85 ? "bg-amber-500" : "bg-teal-600"}`}
                          style={{ width: `${Math.min(100, b.utilization_pct || 0)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* What-If Savings Simulator */}
              <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                <h3 className="text-sm font-bold text-slate-900">What-If Discretionary Budget Simulator</h3>
                <p className="text-xs text-slate-500 mt-1">
                  Simulate how trimming discretionary spending by <b>{simCutPct}%</b> would impact your monthly & annual cash flow if spending actually decreases by that amount:
                </p>
                <input
                  type="range"
                  min={5}
                  max={50}
                  step={5}
                  value={simCutPct}
                  onChange={(e) => setSimCutPct(Number(e.target.value))}
                  className="w-full my-3 accent-teal-600"
                />
                <div className="text-sm font-semibold text-teal-800">
                  Projected Potential Savings: {cur} {Math.round(((overview?.essential_vs_discretionary?.discretionary || 0) * (simCutPct / 100)) / Math.max(1, overview?.available_months?.length || 1)).toLocaleString()} / month
                </div>
              </div>
            </div>
          )}

          {/* 8. FINANCIAL HEALTH SCORE TAB */}
          {activeTab === "health" && health && (
            <div className="space-y-6">
              <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-wrap items-center justify-between gap-6">
                <div className="space-y-2 max-w-2xl">
                  <span className="px-2.5 py-1 bg-teal-50 text-teal-700 rounded-full text-xs font-bold">
                    Educational Budgeting Indicator • Period: {health.data_period}
                  </span>
                  <h2 className="text-xl font-bold text-slate-900">Transparent Financial Health Score</h2>
                  <p className="text-xs text-slate-600">{health.policy_applied}</p>
                </div>
                <div className="text-center px-8 py-5 bg-slate-900 text-white rounded-2xl">
                  <span className="text-xs uppercase text-slate-400">Overall Score</span>
                  <div className="text-4xl font-extrabold text-teal-400 mt-1">
                    {health.overall_score ?? "N/A"} <span className="text-lg text-slate-400">/ 100</span>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                {health.components.map((c: any) => (
                  <div key={c.key} className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
                    <div>
                      <div className="flex justify-between text-xs font-bold text-slate-500">
                        <span>{c.name}</span>
                        <span>{Math.round(c.weight * 100)}% Wt</span>
                      </div>
                      <div className="text-2xl font-bold text-slate-900 mt-2">
                        {c.normalized_score !== null ? `${c.normalized_score}/100` : "Excluded"}
                      </div>
                      <div className="text-xs font-semibold text-teal-700 mt-1">{c.raw_metric}</div>
                      <p className="text-[11px] text-slate-500 mt-2">{c.explanation}</p>
                    </div>
                    <div className="mt-3 pt-2 border-t border-slate-100 text-[10px] font-mono text-slate-400">
                      {c.formula}
                    </div>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-white p-5 rounded-xl border border-slate-200">
                  <h3 className="text-sm font-bold text-emerald-700 mb-2">Positive Financial Indicators</h3>
                  <ul className="space-y-1.5 text-xs text-slate-700 list-disc pl-4">
                    {health.positive_indicators.map((p: string, i: number) => <li key={i}>{p}</li>)}
                  </ul>
                </div>
                <div className="bg-white p-5 rounded-xl border border-slate-200">
                  <h3 className="text-sm font-bold text-amber-700 mb-2">Evidence-Based Improvement Suggestions</h3>
                  <ul className="space-y-1.5 text-xs text-slate-700 list-disc pl-4">
                    {health.improvement_suggestions.map((s: string, i: number) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* 9. REPORTS TAB */}
          {activeTab === "reports" && (
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
              <h2 className="text-base font-bold text-slate-900">Export Verified Financial Reports</h2>
              <p className="text-xs text-slate-500">
                Reports include your selected period ({selectedMonth || "All History"}), category breakdown, recurring commitments, unusual activity review list, and transparent Financial Health Score methodology. No passwords or tokens are ever included.
              </p>
              <div className="flex flex-wrap gap-4 pt-2">
                <button onClick={() => handleExportReport("csv")} className="px-4 py-2.5 bg-slate-900 text-white rounded-lg text-xs font-semibold flex items-center gap-2">
                  <Download className="w-4 h-4" /> Download CSV Transactions
                </button>
                <button onClick={() => handleExportReport("xlsx")} className="px-4 py-2.5 bg-emerald-700 text-white rounded-lg text-xs font-semibold flex items-center gap-2">
                  <Download className="w-4 h-4" /> Download Excel Workbook (.xlsx)
                </button>
                <button onClick={() => handleExportReport("pdf")} className="px-4 py-2.5 bg-teal-600 text-white rounded-lg text-xs font-semibold flex items-center gap-2">
                  <Download className="w-4 h-4" /> Download Formatted PDF Summary
                </button>
              </div>
            </div>
          )}

          {/* 10. SETTINGS & PRIVACY TAB */}
          {activeTab === "settings" && (
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-6">
              <div>
                <h2 className="text-base font-bold text-slate-900">Security, Data Retention & Privacy Controls</h2>
                <p className="text-xs text-slate-500 mt-1">
                  All financial statements are processed locally in your isolated user scope. We never store bank login credentials, PINs, or send your statement text to external cloud AI services.
                </p>
              </div>
              <div className="pt-4 border-t border-slate-200 flex flex-wrap gap-4">
                <button
                  onClick={async () => {
                    if (window.confirm("Permanently purge all uploaded statements and transactions?")) {
                      await fetch(`${API_BASE}/privacy/purge-data`, { method: "DELETE", headers: authHeaders() });
                      await fetchAllData();
                      setStatusBanner("All financial records have been permanently deleted.");
                    }
                  }}
                  className="px-4 py-2 bg-amber-600 text-white rounded-lg text-xs font-semibold flex items-center gap-2"
                >
                  <Trash2 className="w-4 h-4" /> Purge All Uploaded Financial Data
                </button>
                <button
                  onClick={async () => {
                    if (window.confirm("Permanently delete your entire user account and all records?")) {
                      await fetch(`${API_BASE}/privacy/delete-account`, { method: "DELETE", headers: authHeaders() });
                      handleLogout();
                    }
                  }}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg text-xs font-semibold flex items-center gap-2"
                >
                  <Trash2 className="w-4 h-4" /> Delete Entire Account
                </button>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Grounded Conversational Financial Assistant Drawer */}
      {chatOpen && (
        <div className="w-96 bg-white border-l border-slate-200 flex flex-col justify-between p-4 shadow-xl">
          <div>
            <div className="flex justify-between items-center pb-3 border-b border-slate-200">
              <div>
                <h3 className="text-sm font-bold text-slate-900">FinSight Grounded Assistant</h3>
                <span className="text-[10px] text-slate-500">100% Deterministic & Local Data Grounded</span>
              </div>
              <button onClick={() => setChatOpen(false)} className="text-slate-400 font-bold">✕</button>
            </div>

            <div className="my-3 flex flex-wrap gap-1.5">
              {[
                "Where did most of my money go?",
                "How much did I spend on food?",
                "What recurring payments were detected?",
                "Why was this transaction flagged?",
                "What is my current savings rate?",
                "Which categories increased the most?"
              ].map((PromptQ) => (
                <button
                  key={PromptQ}
                  onClick={() => handleAskAssistant(PromptQ)}
                  className="text-[11px] bg-slate-100 hover:bg-teal-50 text-slate-700 px-2.5 py-1 rounded-full"
                >
                  {PromptQ}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto space-y-3 my-2 pr-1">
            {chatHistory.map((m, i) => (
              <div key={i} className={`p-3 rounded-xl text-xs ${m.role === "user" ? "bg-teal-600 text-white ml-6" : "bg-slate-100 text-slate-800 mr-4"}`}>
                <div>{m.text}</div>
                {m.facts && (
                  <div className="mt-2 pt-2 border-t border-slate-200/60 text-[10px] text-slate-500">
                    <b>Grounded Facts ({m.engine}):</b>
                    {m.facts.map((f: string, idx: number) => <div key={idx}>• {f}</div>)}
                  </div>
                )}
              </div>
            ))}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleAskAssistant();
            }}
            className="flex gap-2 pt-2 border-t border-slate-200"
          >
            <input
              type="text"
              value={chatQuestion}
              onChange={(e) => setChatQuestion(e.target.value)}
              placeholder="Ask about your spending, score, or alerts..."
              className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-xs"
            />
            <button type="submit" className="px-3.5 py-2 bg-teal-600 text-white rounded-lg text-xs font-semibold">
              Ask
            </button>
          </form>
        </div>
      )}
    </div>
  );
}