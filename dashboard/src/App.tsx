import { useState, useEffect } from 'react';
import axios from 'axios';
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, LineChart, Line, CartesianGrid } from 'recharts';
import { AlertCircle, CheckCircle2, TrendingUp, Layers, Activity, RefreshCw, FileText } from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const API_URL = '';

type Metrics = {
  matches_breakdown: { name: string; value: number }[];
  total_records: number;
  total_exceptions: number;
  exceptions_by_reason: { reason: string; count: number }[];
  daily_transactions: { date: string; transactions: number }[];
};

type Exception = {
  id: string;
  record_id: string;
  reason: string;
  detail: any;
  created_at: string;
  amount: number;
  reference_date: string;
  raw_reference: string;
  action_recommended?: any;
};

type AuditLog = {
  id: string;
  match_id: string | null;
  decision: string;
  rule_fired: string | null;
  llm_reasoning: string | null;
  created_at: string;
  status: string | null;
  match_type: string | null;
  confidence: number | null;
};

type BankRecord = {
  id: string;
  external_id: string;
  amount: number;
  reference_date: string;
  raw_reference: string;
};

const COLORS = ['#2b84ea', '#0d2366', '#00c17a', '#f36b21', '#ffb020'];

export default function App() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [exceptions, setExceptions] = useState<Exception[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [bankRecords, setBankRecords] = useState<BankRecord[]>([]);
  const [razorpayRecords, setRazorpayRecords] = useState<BankRecord[]>([]);
  const [ledgerRecords, setLedgerRecords] = useState<BankRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'queue' | 'audit' | 'bank'>('overview');
  const [activeDataSource, setActiveDataSource] = useState<'razorpay' | 'bank' | 'ledger'>('razorpay');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const fetchData = async () => {
    setLoading(true);
    try {
      const [mRes, eRes, aRes, bRes, rRes, lRes] = await Promise.all([
        axios.get(`${API_URL}/api/metrics`),
        axios.get(`${API_URL}/api/exceptions`),
        axios.get(`${API_URL}/api/audit`),
        axios.get(`${API_URL}/api/records/bank`),
        axios.get(`${API_URL}/api/records/razorpay`),
        axios.get(`${API_URL}/api/records/ledger`),
      ]);
      setMetrics(mRes.data);
      setExceptions(eRes.data);
      setAuditLogs(aRes.data);
      setBankRecords(bRes.data);
      setRazorpayRecords(rRes.data);
      setLedgerRecords(lRes.data);
    } catch (error) {
      console.error("Failed to fetch data:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const totalMatches = metrics?.matches_breakdown.reduce((sum, m) => sum + m.value, 0) || 0;

  return (
    <div className="min-h-screen bg-rzp-bg text-rzp-text font-sans">
      <header className="sticky top-0 z-50 bg-rzp-dark text-white shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-white/10 p-2 rounded-lg border border-white/20 shadow-inner">
              <Activity className="w-5 h-5 text-white" />
            </div>
            <h1 className="text-xl font-semibold tracking-wide">
              Settlement Reconciliation
            </h1>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => window.open(`${API_URL}/api/export`, '_blank')}
              className="px-4 py-2 bg-rzp-blue hover:bg-blue-600 text-white text-sm font-semibold rounded-lg shadow-md hover:shadow-lg transition-all flex items-center gap-2"
            >
              <FileText className="w-4 h-4" /> Download CSV
            </button>
            <button 
              onClick={fetchData} 
              className="p-2 hover:bg-white/10 rounded-full transition-colors group"
              title="Refresh Data"
            >
              <RefreshCw className={cn("w-5 h-5 text-blue-200 group-hover:text-white", loading && "animate-spin")} />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <MetricCard 
            title="Total Razorpay Batches" 
            value={metrics?.total_records.toString() || "0"} 
            icon={<Layers className="w-6 h-6 text-rzp-blue" />} 
          />
          <MetricCard 
            title="Auto-Resolved Matches" 
            value={totalMatches.toString()} 
            icon={<CheckCircle2 className="w-6 h-6 text-emerald-500" />} 
            trend="+12% since yesterday"
          />
          <MetricCard 
            title="Pending Exceptions" 
            value={metrics?.total_exceptions.toString() || "0"} 
            icon={<AlertCircle className="w-6 h-6 text-rose-500" />} 
            alert={metrics && metrics.total_exceptions > 0}
          />
        </div>

        <div className="flex gap-6 border-b border-rzp-border">
          <button 
            onClick={() => setActiveTab('overview')}
            className={cn("px-2 py-3 text-sm font-semibold transition-colors border-b-2", activeTab === 'overview' ? "border-rzp-blue text-rzp-blue" : "border-transparent text-rzp-textmuted hover:text-rzp-text")}
          >
            Analytics Overview
          </button>
          <button 
            onClick={() => setActiveTab('queue')}
            className={cn("px-2 py-3 text-sm font-semibold transition-colors border-b-2 flex items-center gap-2", activeTab === 'queue' ? "border-rzp-blue text-rzp-blue" : "border-transparent text-rzp-textmuted hover:text-rzp-text")}
          >
            Actionable Queue
            {exceptions.length > 0 && (
              <span className="bg-rose-100 text-rose-600 py-0.5 px-2 rounded-full text-xs">
                {exceptions.length}
              </span>
            )}
          </button>
          <button 
            onClick={() => setActiveTab('audit')}
            className={cn("px-2 py-3 text-sm font-semibold transition-colors border-b-2 flex items-center gap-2", activeTab === 'audit' ? "border-rzp-blue text-rzp-blue" : "border-transparent text-rzp-textmuted hover:text-rzp-text")}
          >
            Compliance Audit
          </button>
          <button 
            onClick={() => setActiveTab('bank')}
            className={cn("px-2 py-3 text-sm font-semibold transition-colors border-b-2 flex items-center gap-2", activeTab === 'bank' ? "border-rzp-blue text-rzp-blue" : "border-transparent text-rzp-textmuted hover:text-rzp-text")}
          >
            Raw Data Explorer
          </button>
        </div>

        {loading ? (
          <div className="h-64 flex items-center justify-center">
            <RefreshCw className="w-8 h-8 text-rzp-blue animate-spin" />
          </div>
        ) : activeTab === 'overview' ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <GlassCard title="Match Breakdown">
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={metrics?.matches_breakdown || []}
                      innerRadius={80}
                      outerRadius={110}
                      paddingAngle={5}
                      dataKey="value"
                      stroke="none"
                    >
                      {metrics?.matches_breakdown.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <RechartsTooltip 
                      contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)' }}
                      itemStyle={{ color: '#2d3748', fontWeight: 500 }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>

            <GlassCard title="Exceptions by Reason">
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={metrics?.exceptions_by_reason || []}>
                    <XAxis dataKey="reason" stroke="#718096" tick={{ fill: '#718096', fontSize: 12 }} axisLine={false} tickLine={false} />
                    <RechartsTooltip 
                      cursor={{ fill: '#f1f5f9' }}
                      contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)' }}
                    />
                    <Bar dataKey="count" fill="#2b84ea" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>

            <GlassCard title="Daily Transaction Volume" className="lg:col-span-2">
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={metrics?.daily_transactions || []}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="date" stroke="#718096" tick={{ fill: '#718096', fontSize: 12 }} axisLine={false} tickLine={false} dy={10} />
                    <YAxis stroke="#718096" tick={{ fill: '#718096', fontSize: 12 }} axisLine={false} tickLine={false} dx={-10} />
                    <RechartsTooltip 
                      contentStyle={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '12px', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)' }}
                    />
                    <Line type="monotone" dataKey="transactions" stroke="#2b84ea" strokeWidth={3} dot={{ r: 4, fill: '#2b84ea' }} activeDot={{ r: 6 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>
          </div>
        ) : activeTab === 'audit' ? (
          <div className="space-y-4">
            {auditLogs.length === 0 ? (
              <div className="text-center py-16 bg-white rounded-2xl shadow-sm border border-rzp-border">
                <div className="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-4">
                  <FileText className="w-8 h-8 text-slate-400" />
                </div>
                <h3 className="text-lg font-medium text-rzp-text">No Audit Logs</h3>
                <p className="text-rzp-textmuted">Run a reconciliation batch to see the system's decisions.</p>
              </div>
            ) : (
              auditLogs.map((log) => (
                <div key={log.id} className="bg-white border border-rzp-border rounded-2xl shadow-sm p-6 hover:shadow-md transition-shadow">
                  <div className="flex items-start justify-between">
                    <div className="space-y-3 max-w-4xl">
                      <div className="flex items-center gap-3">
                        <span className={cn(
                          "px-3 py-1 text-xs font-bold rounded-full uppercase tracking-wider",
                          log.decision === "auto-resolved" ? "bg-emerald-100 text-emerald-700" :
                          log.decision === "human-resolved" ? "bg-blue-100 text-blue-700" :
                          "bg-slate-100 text-slate-700"
                        )}>
                          {log.decision}
                        </span>
                        <span className="text-sm font-medium text-rzp-dark">
                          Match Ref: <span className="font-mono text-xs text-rzp-textmuted ml-1 bg-slate-50 px-2 py-1 rounded">{log.match_id || "N/A"}</span>
                        </span>
                        {log.match_type === 'llm' && (
                          <span className="px-2 py-1 bg-purple-100 text-purple-700 text-xs font-bold rounded">AI ASSISTED</span>
                        )}
                        {log.match_type === 'deterministic' && (
                          <span className="px-2 py-1 bg-slate-100 text-slate-700 text-xs font-bold rounded">DETERMINISTIC</span>
                        )}
                      </div>
                      
                      {log.llm_reasoning && (
                        <div className="text-sm text-rzp-dark bg-blue-50/50 border border-blue-100 p-4 rounded-xl leading-relaxed">
                          <span className="font-semibold text-blue-800 mb-1 block">Decision Context</span>
                          {log.llm_reasoning}
                        </div>
                      )}
                      
                      {log.rule_fired && (
                        <p className="text-sm text-rzp-textmuted font-mono mt-2 flex items-center gap-2">
                          <span className="font-semibold text-rzp-text">Rule:</span> {log.rule_fired}
                        </p>
                      )}
                    </div>
                    <div className="text-right space-y-1">
                      <div className="text-xs text-rzp-textmuted font-medium bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-100">
                        {new Date(log.created_at).toLocaleString()}
                      </div>
                      {log.confidence && (
                        <div className="text-xs font-bold text-rzp-blue mt-2">
                          Confidence: {(log.confidence * 100).toFixed(1)}%
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        ) : activeTab === 'bank' ? (
          <div className="bg-white border border-rzp-border rounded-2xl shadow-sm overflow-hidden flex flex-col">
            <div className="p-5 border-b border-rzp-border bg-slate-50 flex justify-between items-center">
              <div className="flex flex-col gap-3">
                <h3 className="font-semibold text-rzp-dark flex items-center gap-2">
                  <FileText className="w-5 h-5 text-rzp-blue" /> Raw Data Explorer
                </h3>
                <div className="flex gap-2">
                  <button onClick={() => setActiveDataSource('razorpay')} className={cn("px-4 py-1.5 text-xs font-semibold rounded-lg border transition-colors", activeDataSource === 'razorpay' ? "bg-rzp-blue text-white border-rzp-blue" : "bg-white text-rzp-text border-slate-200")}>Razorpay DB</button>
                  <button onClick={() => setActiveDataSource('bank')} className={cn("px-4 py-1.5 text-xs font-semibold rounded-lg border transition-colors", activeDataSource === 'bank' ? "bg-rzp-blue text-white border-rzp-blue" : "bg-white text-rzp-text border-slate-200")}>Bank Statements</button>
                  <button onClick={() => setActiveDataSource('ledger')} className={cn("px-4 py-1.5 text-xs font-semibold rounded-lg border transition-colors", activeDataSource === 'ledger' ? "bg-rzp-blue text-white border-rzp-blue" : "bg-white text-rzp-text border-slate-200")}>Internal Ledger</button>
                </div>
              </div>
              <input
                type="text"
                placeholder="Search by amount or reference..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-72 bg-white border border-slate-300 rounded-lg text-sm px-4 py-2.5 text-rzp-dark focus:outline-none focus:border-rzp-blue focus:ring-1 focus:ring-rzp-blue transition-all shadow-sm"
              />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50/50 text-xs uppercase tracking-wider text-rzp-textmuted font-semibold border-b border-slate-200">
                    <th className="px-6 py-4">Transaction ID (UUID)</th>
                    <th className="px-6 py-4">Reference</th>
                    <th className="px-6 py-4">Date</th>
                    <th className="px-6 py-4 text-right">Amount (₹)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(activeDataSource === 'razorpay' ? razorpayRecords : activeDataSource === 'bank' ? bankRecords : ledgerRecords)
                    .filter(r => 
                      (r.raw_reference && r.raw_reference.toLowerCase().includes(searchQuery.toLowerCase())) || 
                      (r.amount && r.amount.toString().includes(searchQuery))
                    )
                    .map((record) => (
                    <tr key={record.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-3">
                        <div className="font-mono text-xs text-rzp-text">{record.id}</div>
                      </td>
                      <td className="px-6 py-3 text-sm text-rzp-dark font-medium">
                        {record.raw_reference || 'N/A'}
                      </td>
                      <td className="px-6 py-3 text-sm text-rzp-textmuted">
                        {record.reference_date}
                      </td>
                      <td className="px-6 py-3 text-sm text-rzp-dark font-semibold text-right">
                        {record.amount.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                  {(activeDataSource === 'razorpay' ? razorpayRecords : activeDataSource === 'bank' ? bankRecords : ledgerRecords).filter(r => (r.raw_reference && r.raw_reference.toLowerCase().includes(searchQuery.toLowerCase())) || (r.amount && r.amount.toString().includes(searchQuery))).length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-6 py-12 text-center text-rzp-textmuted text-sm">
                        No transactions found matching "{searchQuery}"
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {exceptions.length === 0 ? (
              <div className="text-center py-16 bg-white rounded-2xl shadow-sm border border-rzp-border">
                <div className="w-16 h-16 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4">
                  <CheckCircle2 className="w-8 h-8 text-emerald-500" />
                </div>
                <h3 className="text-lg font-medium text-rzp-text">Queue is Empty</h3>
                <p className="text-rzp-textmuted">All reconciliation exceptions have been resolved successfully.</p>
              </div>
            ) : (
              exceptions.map((exc) => (
                <div key={exc.id} className="bg-white border border-rzp-border rounded-2xl shadow-sm overflow-hidden transition-all duration-200 hover:border-blue-300 hover:shadow-md">
                  <div 
                    className="flex items-center justify-between p-5 cursor-pointer bg-white"
                    onClick={() => setExpandedRow(expandedRow === exc.id ? null : exc.id)}
                  >
                    <div className="flex items-center gap-4">
                      <div className="p-2.5 bg-rose-50 rounded-xl text-rose-500">
                        <AlertCircle className="w-5 h-5" />
                      </div>
                      <div>
                        <h4 className="font-semibold text-rzp-dark text-sm">{exc.record_id}</h4>
                        <p className="text-sm text-rzp-textmuted font-medium mt-0.5 uppercase tracking-wide text-xs">{exc.reason}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-8">
                      <div className="text-right">
                        <div className="font-semibold text-rzp-dark text-lg">₹{exc.amount?.toFixed(2)}</div>
                        <div className="text-xs text-rzp-textmuted font-medium">{exc.reference_date}</div>
                      </div>
                      <div className="text-rzp-blue text-sm font-semibold flex items-center bg-blue-50 px-4 py-2 rounded-lg">
                        {expandedRow === exc.id ? 'Close details' : 'Review Match'}
                      </div>
                    </div>
                  </div>

                  {expandedRow === exc.id && (
                    <div className="px-6 pb-6 pt-4 border-t border-slate-100 bg-slate-50">
                      {exc.action_recommended && (
                        <div className="mb-8 bg-white border border-indigo-200 rounded-xl overflow-hidden shadow-sm">
                           <div className="bg-indigo-50 px-4 py-3 border-b border-indigo-100 flex items-center justify-between">
                             <div className="flex items-center gap-2 text-indigo-800 font-semibold text-sm">
                               <Activity className="w-4 h-4" /> Recommended Recovery Action (Closing the Loop)
                             </div>
                             <span className="text-xs font-mono bg-indigo-100 text-indigo-700 px-2 py-1 rounded">ORCHESTRATOR</span>
                           </div>
                           <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                             <div>
                               <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Action Type</p>
                               <div className="inline-block bg-slate-100 text-slate-700 font-medium text-sm px-3 py-1 rounded-md">
                                 {exc.action_recommended.action_type === 'slack_alert' ? '💬 Slack Ping (Internal)' : 
                                  exc.action_recommended.action_type === 'email_merchant' ? '📧 Email Merchant (External)' : 
                                  '📓 Ledger Adjustment (Auto)'}
                               </div>
                             </div>
                             <div>
                               <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">AI Reasoning</p>
                               <p className="text-sm text-slate-700 italic">"{exc.action_recommended.reasoning}"</p>
                             </div>
                             <div className="md:col-span-2 mt-2">
                               <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Generated System Payload (JSON)</p>
                               <div className="bg-slate-800 text-emerald-400 font-mono text-xs p-3 rounded-lg overflow-x-auto shadow-inner">
                                 <pre>{JSON.stringify(exc.action_recommended.action_payload, null, 2)}</pre>
                               </div>
                             </div>
                           </div>
                           <div className="bg-slate-50 px-4 py-3 border-t border-slate-100 flex justify-end gap-3">
                              <button className="text-slate-600 hover:text-slate-800 text-sm font-semibold px-4 py-2 transition-colors">
                                Dismiss
                              </button>
                              <button className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold px-4 py-2 rounded-lg shadow-sm transition-colors flex items-center gap-2">
                                <CheckCircle2 className="w-4 h-4" /> Execute Action
                              </button>
                           </div>
                        </div>
                      )}

                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                        <div className="space-y-4">
                          <h5 className="text-xs uppercase tracking-wider font-semibold text-rzp-textmuted flex items-center gap-2">
                            <FileText className="w-4 h-4" /> System Context
                          </h5>
                          {exc.detail?.error && (
                            <div className="p-4 bg-rose-50/50 border border-rose-100 rounded-xl text-rose-700 text-sm font-mono whitespace-pre-wrap shadow-inner">
                              {exc.detail.error}
                            </div>
                          )}
                          {exc.detail?.llm_reasoning && (
                            <div className="p-4 bg-blue-50/50 border border-blue-100 rounded-xl text-rzp-dark text-sm italic leading-relaxed shadow-inner">
                              "{exc.detail.llm_reasoning}"
                            </div>
                          )}
                          {exc.raw_reference && (
                             <div className="p-3 bg-slate-200/50 border border-slate-200 rounded-lg text-rzp-dark text-xs font-mono break-all">
                               Raw Ref: {exc.raw_reference}
                             </div>
                          )}
                        </div>
                        
                        <div className="space-y-4">
                          <h5 className="text-xs uppercase tracking-wider font-semibold text-rzp-textmuted">Manual Resolution</h5>
                          <form 
                            onSubmit={async (e) => {
                              e.preventDefault();
                              const formData = new FormData(e.currentTarget);
                              try {
                                await axios.post(`${API_URL}/api/exceptions/${exc.id}/resolve`, {
                                  candidate_id: formData.get('candidate_id'),
                                  notes: formData.get('notes')
                                });
                                fetchData();
                              } catch (err) {
                                alert("Failed to resolve exception");
                              }
                            }}
                            className="space-y-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm"
                          >
                            <div>
                              <label className="block text-xs font-semibold text-rzp-text mb-1.5">Target Bank UUID</label>
                              <input 
                                name="candidate_id"
                                required
                                placeholder="Enter correct matching UUID..." 
                                className="w-full bg-white border border-slate-300 rounded-lg text-sm px-4 py-2.5 text-rzp-dark focus:outline-none focus:border-rzp-blue focus:ring-1 focus:ring-rzp-blue transition-all font-mono shadow-sm"
                              />
                            </div>
                            <div>
                              <label className="block text-xs font-semibold text-rzp-text mb-1.5">Resolution Notes</label>
                              <textarea 
                                name="notes"
                                placeholder="Reason for forcing this match..." 
                                className="w-full bg-white border border-slate-300 rounded-lg text-sm px-4 py-2.5 text-rzp-dark focus:outline-none focus:border-rzp-blue focus:ring-1 focus:ring-rzp-blue transition-all min-h-[80px] shadow-sm"
                              />
                            </div>
                            <button 
                              type="submit"
                              className="w-full bg-rzp-blue hover:bg-blue-600 text-white font-semibold py-2.5 rounded-lg shadow-sm hover:shadow transition-all text-sm"
                            >
                              Confirm Match
                            </button>
                          </form>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function MetricCard({ title, value, icon, trend, alert }: { title: string, value: string, icon: React.ReactNode, trend?: string, alert?: boolean }) {
  return (
    <div className={cn(
      "bg-white border rounded-2xl p-6 shadow-sm relative overflow-hidden transition-all duration-200 hover:shadow-md",
      alert ? "border-rose-200 shadow-rose-100/50" : "border-rzp-border"
    )}>
      <div className="relative flex justify-between items-start">
        <div className="space-y-1">
          <p className="text-sm font-semibold text-rzp-textmuted">{title}</p>
          <p className="text-3xl font-bold tracking-tight text-rzp-dark">{value}</p>
        </div>
        <div className={cn("p-3 rounded-xl shadow-inner", alert ? "bg-rose-50" : "bg-slate-50")}>
          {icon}
        </div>
      </div>
      {trend && (
        <div className="mt-4 flex items-center text-sm font-semibold text-emerald-600 bg-emerald-50 w-fit px-2 py-1 rounded-md">
          <TrendingUp className="w-4 h-4 mr-1.5" /> {trend}
        </div>
      )}
    </div>
  )
}

function GlassCard({ title, children, className }: { title: string, children: React.ReactNode, className?: string }) {
  return (
    <div className={cn("bg-white border border-rzp-border rounded-2xl p-6 shadow-sm hover:shadow-md transition-shadow", className)}>
      <h3 className="text-lg font-bold mb-6 text-rzp-dark flex items-center gap-2">
        <div className="w-1.5 h-6 bg-rzp-blue rounded-full"></div>
        {title}
      </h3>
      {children}
    </div>
  )
}
