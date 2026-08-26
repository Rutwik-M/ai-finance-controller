import os
import json
import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px

# Configuration
st.set_page_config(page_title="Reconciliation Ops", layout="wide", initial_sidebar_state="collapsed")

# Custom minimal CSS for layout polish
st.markdown("""
<style>
    .stAppHeader {display: none;} /* Hide the top header bar */
    div[data-testid="stMetric"] {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 16px;
    }
    .stDataFrame {
        border-radius: 8px;
        border: 1px solid #334155;
        overflow: hidden;
    }
</style>
""", unsafe_allow_html=True)

def get_db_connection():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    return psycopg2.connect(db_url)

def fetch_metrics():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT match_type, count(*) FROM matches GROUP BY match_type")
    matches = cur.fetchall()
    
    cur.execute("SELECT count(*) FROM records WHERE source = 'razorpay'")
    total_records = cur.fetchone()[0]
    
    cur.execute("SELECT count(*) FROM exceptions WHERE status = 'open'")
    total_exceptions = cur.fetchone()[0]
    
    # Exceptions by reason
    cur.execute("SELECT reason, count(*) FROM exceptions WHERE status = 'open' GROUP BY reason")
    exception_reasons = cur.fetchall()
    
    # Transactions over time
    cur.execute("SELECT reference_date::date, count(*) FROM records WHERE source = 'razorpay' GROUP BY reference_date::date ORDER BY reference_date::date")
    daily_txns = cur.fetchall()
    
    cur.close()
    conn.close()
    return matches, total_records, total_exceptions, exception_reasons, daily_txns

def fetch_exceptions():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT e.id, e.record_id, e.reason, e.detail, e.created_at, r.amount, r.reference_date, r.raw_reference
        FROM exceptions e
        JOIN records r ON e.record_id = r.id
        WHERE e.status = 'open'
        ORDER BY e.created_at DESC
    """)
    cols = [desc[0] for desc in cur.description]
    data = cur.fetchall()
    cur.close()
    conn.close()
    if data:
        return pd.DataFrame(data, columns=cols)
    return pd.DataFrame()

def resolve_exception(exception_id, record_id, candidate_id, reasoning):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE exceptions SET status = 'resolved' WHERE id = %s", (exception_id,))
        cur.execute(
            "INSERT INTO audit_log (match_id, decision, llm_reasoning) VALUES (NULL, %s, %s)",
            ("human-resolved", f"Resolved {record_id} to {candidate_id}. Notes: {reasoning}")
        )
        conn.commit()
    except Exception as e:
        st.error(f"Failed to resolve: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

# --- UI Layout ---

st.title(":material/account_balance: Reconciliation Operations")
st.markdown("Monitor and manually resolve escalated settlement batches.")

matches, total_records, total_exceptions, exception_reasons, daily_txns = fetch_metrics()
total_matches = sum(count for _, count in matches) if matches else 0

col1, col2, col3 = st.columns(3)
col1.metric("Total Razorpay Batches", total_records)
col2.metric("Auto-Resolved Matches", total_matches)
col3.metric("Pending Exceptions", total_exceptions)

st.markdown("---")

tab1, tab2 = st.tabs(["📊 Analytics Overview", "📝 Exceptions Queue"])

with tab1:
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.subheader(":material/pie_chart: Match Breakdown")
        if matches:
            df_matches = pd.DataFrame(matches, columns=["Match Type", "Count"])
            fig1 = px.pie(df_matches, values="Count", names="Match Type", hole=0.5, 
                         color_discrete_sequence=['#3b82f6', '#8b5cf6', '#10b981'])
            fig1.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=20, b=20, l=20, r=20)
            )
            st.plotly_chart(fig1, use_container_width=True)
        else:
            st.info("No matches found yet.")
            
    with chart_col2:
        st.subheader(":material/warning: Exceptions by Reason")
        if exception_reasons:
            df_reasons = pd.DataFrame(exception_reasons, columns=["Reason", "Count"])
            fig2 = px.bar(df_reasons, x="Reason", y="Count", color="Reason",
                          color_discrete_sequence=px.colors.qualitative.Pastel)
            fig2.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=20, b=20, l=20, r=20),
                showlegend=False
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.success("No exceptions found.")
            
    st.subheader(":material/show_chart: Daily Transaction Volume")
    if daily_txns:
        df_txns = pd.DataFrame(daily_txns, columns=["Date", "Transactions"])
        fig3 = px.line(df_txns, x="Date", y="Transactions", markers=True,
                       line_shape='spline')
        fig3.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=20, l=20, r=20)
        )
        fig3.update_traces(line_color='#3b82f6', line_width=3, marker_size=8)
        st.plotly_chart(fig3, use_container_width=True)

with tab2:
    st.subheader(":material/list_alt: Actionable Queue")
    df_exc = fetch_exceptions()
    
    if not df_exc.empty:
        st.dataframe(
            df_exc[['record_id', 'reason', 'amount', 'reference_date']], 
            use_container_width=True, hide_index=True
        )
        
        st.markdown("### :material/gavel: Resolve Exceptions")
        for idx, row in df_exc.iterrows():
            with st.expander(f"Review Record: {row['record_id']} ({row['reason']})"):
                st.write(f"**Target Amount:** ₹{row['amount']} | **Date:** {row['reference_date']}")
                
                try:
                    detail = json.loads(row['detail'])
                    if 'error' in detail:
                        st.error(f"**System Error:** {detail['error']}")
                    if 'llm_reasoning' in detail:
                        st.info(f"**LLM Output:** {detail['llm_reasoning']}")
                    if 'candidates' in detail:
                        st.write(f"**Candidates Evaluated:** {detail['candidates']}")
                except:
                    st.write(row['detail'])
                
                with st.form(key=f"form_{row['id']}"):
                    candidate_id = st.text_input("Override Bank Candidate UUID", placeholder="Enter the correct Bank UUID...")
                    notes = st.text_area("Resolution Notes", placeholder="Why are you manually forcing this match?")
                    if st.form_submit_button("Confirm Resolution", type="primary"):
                        resolve_exception(row['id'], row['record_id'], candidate_id, notes)
                        st.success("Resolved successfully! Please refresh.")
    else:
        st.success("No pending exceptions! The queue is entirely clear.")
