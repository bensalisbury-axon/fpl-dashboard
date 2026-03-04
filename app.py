import streamlit as st
import requests
import pandas as pd
import plotly.express as px

# ── Config ───────────────────────────────────────────────────────────────────
LEAGUES = {
    "Henry scares me sometimes": 690265,
    "Cuzzie Boys": 768435,
}

BASE_URL = "https://fantasy.premierleague.com/api/"

# ── API helpers ───────────────────────────────────────────────────────────────
def _get(endpoint: str) -> dict:
    url = BASE_URL + endpoint
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=300)
def get_bootstrap() -> dict:
    return _get("bootstrap-static/")


@st.cache_data(ttl=300)
def get_league_standings(league_id: int) -> pd.DataFrame:
    """Fetch all standings pages and return a single DataFrame."""
    results = []
    page = 1
    while True:
        data = _get(f"leagues-classic/{league_id}/standings/?page_standings={page}")
        results.extend(data["standings"]["results"])
        if not data["standings"]["has_next"]:
            break
        page += 1
    return pd.DataFrame(results)


@st.cache_data(ttl=300)
def get_manager_history(entry_id: int) -> pd.DataFrame:
    data = _get(f"entry/{entry_id}/history/")
    return pd.DataFrame(data["current"])


@st.cache_data(ttl=300)
def get_picks(entry_id: int, gw: int) -> list:
    data = _get(f"entry/{entry_id}/event/{gw}/picks/")
    return data["picks"]


@st.cache_data(ttl=300)
def get_manager_transfers(entry_id: int) -> pd.DataFrame:
    data = _get(f"entry/{entry_id}/transfers/")
    return pd.DataFrame(data) if data else pd.DataFrame()


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FPL League Dashboard",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ FPL League Dashboard")

# ── League selector ───────────────────────────────────────────────────────────
selected_league_name = st.radio(
    "League",
    options=list(LEAGUES.keys()),
    horizontal=True,
)
selected_league_id = LEAGUES[selected_league_name]

st.divider()

# ── Load core data ────────────────────────────────────────────────────────────
with st.spinner("Loading league data…"):
    try:
        bootstrap = get_bootstrap()
        standings_df = get_league_standings(selected_league_id)
    except Exception as e:
        st.error(f"Failed to load data: {e}")
        st.stop()

# Remove managers who can no longer access their account
EXCLUDED_MANAGERS = {"poojstar"}
standings_df = standings_df[~standings_df["player_name"].str.lower().isin(EXCLUDED_MANAGERS)]

# Players lookup table
players_raw = pd.DataFrame(bootstrap["elements"])[
    ["id", "web_name", "team", "element_type", "now_cost"]
].copy()
players_raw["now_cost"] = players_raw["now_cost"] / 10

teams_raw = pd.DataFrame(bootstrap["teams"])[["id", "name", "short_name"]]
players_df = players_raw.merge(
    teams_raw.rename(columns={"id": "team", "name": "team_name", "short_name": "team_short"}),
    on="team",
    how="left",
)
players_df["position"] = players_df["element_type"].map(
    {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
)

# Current gameweek
gws_df = pd.DataFrame(bootstrap["events"])
current_row = gws_df[gws_df["is_current"] == True]
if current_row.empty:
    current_row = gws_df[gws_df["finished"] == True]
current_gw = int(current_row["id"].iloc[-1]) if not current_row.empty else 1

# ── Standings ─────────────────────────────────────────────────────────────────
st.subheader(f"🏆 Standings after GW{current_gw}")

display_df = (
    standings_df[["rank", "last_rank", "entry_name", "total", "event_total"]]
    .copy()
    .rename(columns={
        "rank": "Rank",
        "last_rank": "Last GW Rank",
        "entry_name": "Team",
        "total": "Total Pts",
        "event_total": f"GW{current_gw} Pts",
    })
)

def movement(row):
    diff = row["Last GW Rank"] - row["Rank"]
    if diff > 0:
        return f"▲ {diff}"
    elif diff < 0:
        return f"▼ {abs(diff)}"
    return "–"

display_df.insert(1, "Move", display_df.apply(movement, axis=1))
display_df = display_df.drop(columns=["Last GW Rank"])

def highlight_top3(row):
    colors = {1: "background-color: #DAA520", 2: "background-color: #C0C0C0", 3: "background-color: #CD7F32"}
    return [colors.get(row["Rank"], "")] * len(row)

def colour_move(val):
    if str(val).startswith("▲"):
        return "color: #2ECC71; font-weight: bold"
    elif str(val).startswith("▼"):
        return "color: #E74C3C; font-weight: bold"
    return ""

st.dataframe(
    display_df.style.apply(highlight_top3, axis=1).map(colour_move, subset=["Move"]),
    use_container_width=True,
    hide_index=True,
)

st.divider()

# ── Transfer News ─────────────────────────────────────────────────────────────
st.subheader(f"🔄 Transfer News — GW{current_gw}")

player_id_to_name = players_df.set_index("id")["web_name"].to_dict()

with st.spinner("Loading transfer activity…"):
    transfer_rows = []
    for _, row in standings_df.iterrows():
        try:
            transfers = get_manager_transfers(int(row["entry"]))
            if not transfers.empty and "event" in transfers.columns:
                gw_transfers = transfers[transfers["event"] == current_gw].copy()
                if not gw_transfers.empty:
                    gw_transfers["Team"] = row["entry_name"]
                    gw_transfers["Manager"] = row["player_name"]
                    transfer_rows.append(gw_transfers)
        except Exception:
            pass

if transfer_rows:
    all_transfers = pd.concat(transfer_rows, ignore_index=True)
    all_transfers["Transferred Out"] = all_transfers["element_out"].map(player_id_to_name)
    all_transfers["Transferred In"] = all_transfers["element_in"].map(player_id_to_name)
    all_transfers["Bought For"] = all_transfers["element_in_cost"].apply(lambda x: f"£{x/10:.1f}m")
    all_transfers["Sold For"] = all_transfers["element_out_cost"].apply(lambda x: f"£{x/10:.1f}m")
    st.dataframe(
        all_transfers[["Team", "Transferred Out", "Sold For", "Transferred In", "Bought For"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info(f"No transfers made in GW{current_gw} yet.")

st.divider()

# ── Captain Choices ───────────────────────────────────────────────────────────
st.subheader(f"🎖️ Captain Choices — GW{current_gw}")

with st.spinner("Loading captain selections…"):
    captain_rows = []
    for _, row in standings_df.iterrows():
        try:
            picks = get_picks(int(row["entry"]), current_gw)
            for pick in picks:
                if pick["is_captain"]:
                    captain_name = player_id_to_name.get(pick["element"], "Unknown")
                    label = f"{captain_name} (TC)" if pick["multiplier"] == 3 else captain_name
                    captain_rows.append({
                        "Team": row["entry_name"],
                        "Captain": label,
                    })
                    break
        except Exception:
            pass

if captain_rows:
    captains_df = pd.DataFrame(captain_rows)
    st.dataframe(captains_df, use_container_width=True, hide_index=True)
else:
    st.info("Captain data not available yet for this gameweek.")

st.divider()

# ── Points Over Time ──────────────────────────────────────────────────────────
st.subheader("📈 Points Over Time")

with st.spinner("Fetching GW history for all managers…"):
    history_rows = []
    errors = []
    for _, row in standings_df.iterrows():
        try:
            hist = get_manager_history(int(row["entry"]))
            hist = hist.copy()
            hist["Manager"] = row["player_name"]
            hist["Team"] = row["entry_name"]
            history_rows.append(hist)
        except Exception as e:
            errors.append(f"{row['player_name']}: {e}")

if errors:
    with st.expander("⚠️ Some managers could not be loaded"):
        for err in errors:
            st.write(err)

if history_rows:
    all_history = pd.concat(history_rows, ignore_index=True)

    fig_line = px.line(
        all_history,
        x="event",
        y="total_points",
        color="Team",
        markers=True,
        labels={"event": "Gameweek", "total_points": "Cumulative Points"},
        title="Cumulative Points by Gameweek",
    )
    fig_line.update_layout(hovermode="x unified", legend_title_text="Team")
    st.plotly_chart(fig_line, use_container_width=True)

    fig_rank = px.line(
        all_history,
        x="event",
        y="overall_rank",
        color="Team",
        markers=True,
        labels={"event": "Gameweek", "overall_rank": "Global Rank"},
        title="Global Rank Over Time",
    )
    fig_rank.update_layout(
        hovermode="x unified",
        legend_title_text="Team",
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig_rank, use_container_width=True)

    fig_bar = px.bar(
        all_history,
        x="event",
        y="points",
        color="Team",
        barmode="group",
        labels={"event": "Gameweek", "points": "GW Points"},
        title="Points per Gameweek",
    )
    fig_bar.update_layout(legend_title_text="Team")
    st.plotly_chart(fig_bar, use_container_width=True)

    pivot = all_history.pivot_table(
        index="Team", columns="event", values="points", aggfunc="sum"
    )
    pivot.columns = [f"GW{c}" for c in pivot.columns]
    st.dataframe(pivot, use_container_width=True)

    st.subheader("🪑 Points Left on Bench")
    bench_total = (
        all_history.groupby("Team")["points_on_bench"]
        .sum()
        .reset_index()
        .rename(columns={"points_on_bench": "Total Bench Points"})
        .sort_values("Total Bench Points", ascending=False)
    )
    fig_bench_bar = px.bar(
        bench_total,
        x="Team",
        y="Total Bench Points",
        color="Team",
        title="Total Points Left on Bench (Season)",
        labels={"Total Bench Points": "Points"},
    )
    fig_bench_bar.update_layout(showlegend=False)
    fig_bench_bar.update_traces(texttemplate="%{y}", textposition="inside", textfont_color="black")
    st.plotly_chart(fig_bench_bar, use_container_width=True)

    bench_leaderboard = (
        all_history[["Team", "event", "points_on_bench"]]
        .rename(columns={"event": "GW", "points_on_bench": "Bench Points"})
        .sort_values("Bench Points", ascending=False)
        .head(10)
        .reset_index(drop=True)
    )
    bench_leaderboard.index += 1
    st.dataframe(bench_leaderboard, use_container_width=True)

    st.subheader("🏅 Best & Worst Gameweeks")
    finished_history = all_history[all_history["event"] < current_gw]
    idx_best = all_history.groupby("Team")["points"].idxmax()
    idx_worst = finished_history.groupby("Team")["points"].idxmin()
    best = all_history.loc[idx_best, ["Team", "event", "points"]].rename(
        columns={"event": "Best GW", "points": "Best Pts"}
    )
    worst = finished_history.loc[idx_worst, ["Team", "event", "points"]].rename(
        columns={"event": "Worst GW", "points": "Worst Pts"}
    )
    bw_df = (
        best.merge(worst[["Team", "Worst GW", "Worst Pts"]], on="Team")
        .sort_values("Best Pts", ascending=False)
        .reset_index(drop=True)
    )
    bw_df.index += 1
    st.dataframe(
        bw_df,
        use_container_width=True,
        column_config={"Team": st.column_config.Column(pinned=True)},
    )
else:
    st.warning("No history data could be loaded.")

st.divider()

# ── Squad Picks ───────────────────────────────────────────────────────────────
st.subheader("👕 Squad Picks")

col1, col2 = st.columns([2, 1])
with col1:
    manager_map = dict(zip(standings_df["player_name"], standings_df["entry"]))
    selected_manager = st.selectbox("Select a manager", list(manager_map.keys()))
with col2:
    gw_select = st.number_input("Gameweek", min_value=1, max_value=38, value=current_gw, step=1)

with st.spinner(f"Loading GW{gw_select} picks…"):
    try:
        picks_data = _get(f"entry/{int(manager_map[selected_manager])}/event/{int(gw_select)}/picks/")
        picks_raw = picks_data["picks"]
        entry_hist = picks_data.get("entry_history", {})
        squad_value = entry_hist.get("value", 0) / 10
        bank = entry_hist.get("bank", 0) / 10
        st.caption(f"Squad value: £{squad_value:.1f}m  |  In bank: £{bank:.1f}m  |  Total: £{squad_value + bank:.1f}m")
        picks_df = pd.DataFrame(picks_raw).rename(columns={"position": "lineup_pos"})
        picks_df = picks_df.merge(
            players_df[["id", "web_name", "team_name", "position", "now_cost"]],
            left_on="element",
            right_on="id",
            how="left",
        )

        pos_order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
        picks_df["pos_sort"] = picks_df["position"].map(pos_order)

        starting_xi = picks_df[picks_df["multiplier"] > 0].sort_values(["pos_sort", "lineup_pos"])
        bench = picks_df[picks_df["multiplier"] == 0].sort_values("lineup_pos")

        def format_picks(df: pd.DataFrame) -> pd.DataFrame:
            out = df[["position", "web_name", "team_name", "now_cost", "is_captain", "is_vice_captain"]].copy()
            out["Captain"] = out.apply(
                lambda r: "C" if r["is_captain"] else ("VC" if r["is_vice_captain"] else ""), axis=1
            )
            out = out.drop(columns=["is_captain", "is_vice_captain"])
            out = out.rename(columns={
                "position": "Pos",
                "web_name": "Player",
                "team_name": "Club",
                "now_cost": "Price (£m)",
            })
            return out.reset_index(drop=True)

        st.markdown("**Starting XI**")
        st.dataframe(format_picks(starting_xi), use_container_width=True, hide_index=True)

        st.markdown("**Bench**")
        st.dataframe(format_picks(bench), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Could not load picks for GW{gw_select}: {e}")
        st.info("This gameweek may not have happened yet, or the manager hadn't made picks.")

st.divider()

# ── League Template ───────────────────────────────────────────────────────────
st.subheader(f"👥 League Template — GW{current_gw}")
st.caption("Players owned by the most managers in the league right now")

with st.spinner("Loading squad data for all managers…"):
    template_counts: dict[int, int] = {}
    for _, row in standings_df.iterrows():
        try:
            picks = get_picks(int(row["entry"]), current_gw)
            for pick in picks:
                pid = pick["element"]
                template_counts[pid] = template_counts.get(pid, 0) + 1
        except Exception:
            pass

if template_counts:
    n_managers = len(standings_df)
    all_template = (
        pd.DataFrame(list(template_counts.items()), columns=["id", "Owners"])
        .merge(players_df[["id", "web_name", "team_name", "position", "now_cost"]], on="id", how="left")
        .assign(**{"Ownership %": lambda df: (df["Owners"] / n_managers * 100).round(0).astype(int)})
        .rename(columns={"web_name": "Player", "team_name": "Club", "position": "Pos", "now_cost": "Price (£m)"})
    )
    pos_quota = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    pos_order = ["GKP", "DEF", "MID", "FWD"]
    template_df = pd.concat([
        all_template[all_template["Pos"] == pos]
        .sort_values("Owners", ascending=False)
        .head(quota)
        for pos, quota in pos_quota.items()
    ])
    template_df = (
        template_df
        .sort_values("Owners", ascending=False)
        [["Player", "Club", "Pos", "Price (£m)", "Ownership %"]]
        .reset_index(drop=True)
    )
    template_df.index += 1
    st.dataframe(template_df, use_container_width=True, height=35 * 15 + 38)
else:
    st.info("Could not load template data for this gameweek.")
