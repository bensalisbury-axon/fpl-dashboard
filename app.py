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

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["🏆 Standings", "📈 Points Over Time", "👕 Squad Picks"])

# ── Tab 1: Standings ──────────────────────────────────────────────────────────
with tab1:
    st.subheader(f"{selected_league_name} — Standings after GW{current_gw}")

    display_df = (
        standings_df[["rank", "last_rank", "entry_name", "player_name", "total", "event_total"]]
        .copy()
        .rename(columns={
            "rank": "Rank",
            "last_rank": "Last GW Rank",
            "entry_name": "Team",
            "player_name": "Manager",
            "total": "Total Pts",
            "event_total": f"GW{current_gw} Pts",
        })
    )

    # Movement arrow column
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
        colors = {1: "background-color: #FFD700", 2: "background-color: #C0C0C0", 3: "background-color: #CD7F32"}
        return [colors.get(row["Rank"], "")] * len(row)

    st.dataframe(
        display_df.style.apply(highlight_top3, axis=1),
        use_container_width=True,
        hide_index=True,
    )

# ── Tab 2: Points Over Time ───────────────────────────────────────────────────
with tab2:
    st.subheader(f"{selected_league_name} — Cumulative Points Over Time")

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

        # Cumulative points line chart
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

        # GW-by-GW bar chart
        st.subheader("Points per Gameweek")
        fig_bar = px.bar(
            all_history,
            x="event",
            y="points",
            color="Team",
            barmode="group",
            labels={"event": "Gameweek", "points": "GW Points"},
            title="Gameweek Points",
        )
        fig_bar.update_layout(legend_title_text="Team")
        st.plotly_chart(fig_bar, use_container_width=True)

        # Mini league table (GW scores pivot)
        st.subheader("GW Score Grid")
        pivot = all_history.pivot_table(
            index="Team", columns="event", values="points", aggfunc="sum"
        )
        pivot.columns = [f"GW{c}" for c in pivot.columns]
        st.dataframe(pivot.style.background_gradient(cmap="RdYlGn", axis=None), use_container_width=True)
    else:
        st.warning("No history data could be loaded.")

# ── Tab 3: Squad Picks ────────────────────────────────────────────────────────
with tab3:
    st.subheader("Manager Squad Picks")

    col1, col2 = st.columns([2, 1])
    with col1:
        manager_map = dict(zip(standings_df["player_name"], standings_df["entry"]))
        selected_manager = st.selectbox("Select a manager", list(manager_map.keys()))
    with col2:
        gw_select = st.number_input("Gameweek", min_value=1, max_value=38, value=current_gw, step=1)

    with st.spinner(f"Loading GW{gw_select} picks…"):
        try:
            picks_raw = get_picks(int(manager_map[selected_manager]), int(gw_select))
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
                out = df[["position", "web_name", "team_name", "now_cost", "multiplier", "is_captain", "is_vice_captain"]].copy()
                out["Captain"] = out.apply(
                    lambda r: "C" if r["is_captain"] else ("VC" if r["is_vice_captain"] else ""), axis=1
                )
                out = out.drop(columns=["is_captain", "is_vice_captain"])
                out = out.rename(columns={
                    "position": "Pos",
                    "web_name": "Player",
                    "team_name": "Club",
                    "now_cost": "Price (£m)",
                    "multiplier": "Mult",
                })
                return out.reset_index(drop=True)

            st.markdown("**Starting XI**")
            st.dataframe(format_picks(starting_xi), use_container_width=True, hide_index=True)

            st.markdown("**Bench**")
            st.dataframe(format_picks(bench), use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Could not load picks for GW{gw_select}: {e}")
            st.info("This gameweek may not have happened yet, or the manager hadn't made picks.")
