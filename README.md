# Dynamic Server Scaling: Performance and Cost Under Variable Workloads

**Original Swedish Title:** *Dynamisk serverskalning: prestanda och kostnad vid varierande belastning*  
**University:** University West (*Högskolan Väst*), Sweden  
**Course:** DTA400 – Network Simulation (Autumn 2026)  
**Project Members:** Shucayb Said & Firat Kaya  
**Technology Stack:** Python 3, SimPy 4.1.2, NumPy, Pandas, Matplotlib, Pytest  
**GitHub Repository:** [https://github.com/SAS2005/Project-DTA400](https://github.com/SAS2005/Project-DTA400)

---

## 1. Project Overview and Objectives

Web applications hosted in cloud environments experience non-stationary request arrival rates, including diurnal load variations, sustained high-load phases, and sudden traffic spikes. Static capacity provisioning forces an unfavorable trade-off: provisioning for peak demand yields low resource utilization and high operating costs, whereas provisioning for average demand causes severe First-In, First-Out (FIFO) queue buildup and Service Level Objective (SLO) violations during traffic surges.

This project designs, implements, tests, and evaluates a reproducible **discrete-event simulation (DES)** in Python and **SimPy** to investigate how a web application backend dynamically adjusts server capacity under variable workloads. We compare **Vertical Scaling**, **Horizontal Scaling**, **Hybrid Scaling**, and an **Adaptive Hybrid** variant against fixed static baselines (`static_1`, `static_2`, `static_4`), quantifying the trade-offs among:

- **Response time** (mean, median/P50, 95th-percentile/P95, P99, and maximum latency)
- **Waiting time** vs. **service execution time**
- **Arrival-window throughput** vs. **end-to-end completion rate** (accounting for post-arrival queue draining)
- **Time-weighted server utilization** and **FIFO queue length**
- **Cold-start / upgrade provisioning delays**, **warm standby operation**, and **delayed shutdown windows**
- **Normalized operating cost** and **per-seed vs. mean-based SLO compliance**

---

## 2. Official Research Questions

The experimental suite answers the three approved research questions using multi-seed empirical measurements ($N = 10$ independent stochastic replications per configuration, seeds `42..51`):

- **RQ1:** *Which scaling strategy achieves the lowest estimated operating cost while satisfying a defined response-time objective?*
- **RQ2:** *How do startup delays, standby operation, and delayed shutdown affect server cost and response time during traffic spikes?*
- **RQ3:** *Under which conditions is hybrid scaling more cost-effective than either vertical or horizontal scaling alone?*

---

## 3. System Architecture

The simulator is structured into five modular logical components:

```text
+--------------------+      +--------------------+      +--------------------+
| 1. Traffic         | ---> | 2. Request Queue   | ---> | 3. Server Pool     |
|    Generator       |      |    (FIFO + Int.)   |      |    (Instances)     |
+--------------------+      +--------------------+      +--------------------+
                                      |                           |
                                      v                           v
                            +--------------------+      +--------------------+
                            | 4. Autoscaler      | ---> | 5. Metrics & Cost  |
                            |    (Controller)    |      |    Collector       |
                            +--------------------+      +--------------------+
```

1. **Traffic Generator (`workload.py`):** Generates synthetic HTTP-style requests using a seeded piecewise-constant non-homogeneous Poisson process ($\text{Exp}(1/\lambda(t))$ inter-arrival times with strict segment-boundary truncation so old arrival rates never leak across phase transitions). Identical pre-generated request streams (`clone_workload`) are replayed across all compared strategies for each seed (Common Random Numbers).
2. **Request Queue (`server.py` – `RequestQueue`):** A centralized FIFO waiting queue that records queue entry timestamps, tracks an exact continuous-time integral $\int Q(t)\,dt$ for time-weighted queue length calculation, and dispatches waiting requests as soon as an eligible active server becomes free.
3. **Server Pool (`server.py` – `ServerPool` & `ServerInstance`):** Models server instances across five explicit lifecycle states (`STOPPED`, `BOOTING`, `ACTIVE`, `DRAINING`, `STANDBY`). An `ACTIVE` server with processing capacity $c$ executes one request of work $W$ at a time in non-preemptive service time $t_s = W / c$. Busy servers are never interrupted during scale-down: they enter `DRAINING` (ceasing to accept new requests) and transition to `STANDBY` or `STOPPED` only after finishing their in-flight request.
4. **Autoscaler (`scaling.py` – `Autoscaler`):** Evaluates window-integrated utilization and queue buildup every $5.0\text{ s}$ up to the end of the arrival horizon ($3,600\text{ s}$). Triggers scale-up when window utilization $\ge 0.85$ or when the waiting queue builds up ($\ge 2$ requests across $2$ consecutive $5\text{ s}$ checks), and triggers scale-down when window utilization $\le 0.35$ with an empty queue continuously for $60.0\text{ s}$, subject to a $60.0\text{ s}$ scaling cooldown.
5. **Metrics and Cost Collector (`metrics.py` – `MetricsCollector`):** Performs exact event-driven continuous-time integration of active capacity-seconds, booting/upgrade provisioning capacity-seconds, standby capacity-seconds, and busy CPU-seconds across the entire simulation run (including any post-arrival drain phase), without double counting.

---

## 4. Workload Model and Request Classes

### Request Types (`config.py` – `DEFAULT_REQUEST_CLASSES`)
Each arriving request is assigned a computational work requirement $W$ (in normalized CPU-seconds on a 1-unit server):
- **Small (`small`):** Probability $0.50$, CPU work $W = 0.05\text{ CPU-s}$
- **Medium (`medium`):** Probability $0.35$, CPU work $W = 0.15\text{ CPU-s}$
- **Heavy (`heavy`):** Probability $0.15$, CPU work $W = 0.35\text{ CPU-s}$

The expected work per request is $\mathbb{E}[W] = 0.50(0.05) + 0.35(0.15) + 0.15(0.35) = 0.13\text{ CPU-s}$, corresponding to a maximum sustainable service rate of $\mu_1 = 1 / 0.13 \approx 7.69\text{ req/s}$ per unit of capacity.

### Traffic Scenarios (`config.py` – `TRAFFIC_SCENARIOS`)
1. **`variable_baseline` (60-minute primary profile):**
   - `0–600 s` ($0–10\text{ min}$): **Low** ($\lambda = 3.0\text{ req/s}$, mean demand $0.39\text{ units}$)
   - `600–1500 s` ($10–25\text{ min}$): **Normal** ($\lambda = 6.0\text{ req/s}$, mean demand $0.78\text{ units}$)
   - `1500–2100 s` ($25–35\text{ min}$): **High** ($\lambda = 12.0\text{ req/s}$, mean demand $1.56\text{ units}$)
   - `2100–2220 s` ($35–37\text{ min}$): **Traffic Spike** ($\lambda = 20.0\text{ req/s}$, mean demand $2.60\text{ units}$)
   - `2220–3000 s` ($37–50\text{ min}$): **Normal** ($\lambda = 6.0\text{ req/s}$, mean demand $0.78\text{ units}$)
   - `3000–3600 s` ($50–60\text{ min}$): **Low** ($\lambda = 3.0\text{ req/s}$, mean demand $0.39\text{ units}$)
2. **`steady_low`:** Constant $\lambda = 3.0\text{ req/s}$ over $3,600\text{ s}$.
3. **`steady_normal`:** Constant $\lambda = 6.0\text{ req/s}$ over $3,600\text{ s}$.
4. **`steady_high`:** Constant $\lambda = 12.0\text{ req/s}$ over $3,600\text{ s}$.
5. **`sudden_spike`:** Low ($3\text{ req/s}$, $0–600\text{ s}$) $\to$ Normal ($6\text{ req/s}$, $600–1500\text{ s}$) $\to$ Sudden Spike ($20\text{ req/s}$, $1500–1680\text{ s}$) $\to$ Normal ($6\text{ req/s}$, $1680–3000\text{ s}$) $\to$ Low ($3\text{ req/s}$, $3000–3600\text{ s}$).
6. **`recurring_spikes`:** Six $20\text{ req/s}$ spikes separated by short ($45\text{ s}$) and medium ($90\text{ s}$) lulls ($\lambda = 2\text{ req/s}$) to test warm standby and shutdown delay sensitivity.

---

## 5. Scaling Strategies and Static Baselines

All dynamic strategies share identical minimum capacity ($1.0\text{ unit}$), maximum capacity ($4.0\text{ units}$), monitoring interval ($5.0\text{ s}$), utilization thresholds ($0.85$ up / $0.35$ down), scale-down observation window ($60.0\text{ s}$), and cooldown ($60.0\text{ s}$):

| Strategy ID | Configuration (Servers $\times$ Capacity) | Capacity Tiers | Max Parallel Jobs | Single-Job Speedup ($W/c$) | Provisioning Delay |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `static_1` | **1 server $\times$ 1.0 unit** (fixed) | $\{1\}$ | 1 | $1\times$ | None |
| `static_2` (`static_vertical_2`) | **1 server $\times$ 2.0 units** (fixed single-server baseline) | $\{2\}$ | 1 | $2\times$ | None |
| `static_4` (`static_vertical_4`) | **1 server $\times$ 4.0 units** (fixed single-server baseline) | $\{4\}$ | 1 | $4\times$ | None |
| `static_horizontal_2` | **2 servers $\times$ 1.0 unit** (fixed multi-server baseline) | $\{2\}$ | 2 | $1\times$ | None |
| `static_horizontal_4` | **4 servers $\times$ 1.0 unit** (fixed multi-server baseline) | $\{4\}$ | 4 | $1\times$ | None |
| `vertical` | **1 server** resized across $1.0 \leftrightarrow 2.0 \leftrightarrow 4.0$ | $\{1, 2, 4\}$ | 1 | Up to $4\times$ | $5.0\text{ s}$ live upgrade |
| `horizontal` | **1 to 4 servers** of $1.0\text{ unit}$ each ($1\times 1 \leftrightarrow \dots \leftrightarrow 4\times 1$) | $\{1, 2, 3, 4\}$ | Up to 4 | $1\times$ | $10.0\text{ s}$ cold / $2.0\text{ s}$ warm |
| `hybrid` | **Vertical first, then horizontal:** $1\times 1 \leftrightarrow 1\times 2 \leftrightarrow 2\times 2$ | $\{1, 2, 4\}$ | Up to 2 | Up to $2\times$ | $5.0\text{ s}$ vert / $10.0\text{ s}$ horiz |
| `hybrid_adaptive` | **Adaptive hybrid with 3-unit tier:** $[1] \leftrightarrow [2] \leftrightarrow [2,1] \leftrightarrow [2,2]$ | $\{1, 2, 3, 4\}$ | Up to 2 | Up to $2\times$ | $5.0\text{ s}$ vert / $10.0\text{ s}$ horiz |

*(Note on Static Baselines: In Experiment 1, `static_1`, `static_2`, and `static_4` represent single-server static baselines with capacities $1.0$, $2.0$, and $4.0$ units, respectively. Multi-instance static baselines `static_horizontal_2` and `static_horizontal_4` are also implemented and verified in `scaling.py` and `tests/test_scaling.py`.)*

---

## 6. Simulation Duration, Drain Phase, and Throughput Definitions

- **Arrival Horizon (`simulation_duration_s`):** New requests arrive over $[0, 3600.0\text{ s}]$. At $t = 3,600.0\text{ s}$, new arrivals and periodic autoscaler checks stop.
- **Post-Arrival Drain Phase (`drain_duration_s`):** Any requests remaining in the FIFO queue or in service at $t = 3,600.0\text{ s}$ continue processing until completion (up to `max_drain_time = 1800.0 s`). Total elapsed simulated time is $T_{\text{elapsed}} = \max(t_{\text{end}}, 3600.0\text{ s})$.
- **Throughput Definitions:**
  1. **Arrival-Window Throughput (`arrival_window_throughput_req_per_s`):** Requests completed within $[0, 3600.0\text{ s}]$ divided by $3,600.0\text{ s}$.
  2. **End-to-End Completion Rate (`end_to_end_completion_rate_req_per_s` and `throughput_req_per_s`):** All completed requests (including drain completions) divided by the actual total elapsed time $T_{\text{elapsed}}$.
- **Cost Integration Horizon:** Operating costs (`active_cost`, `provisioning_cost`, `standby_cost`) are integrated continuously over the entire elapsed time $[0, T_{\text{elapsed}}]$, including the drain phase.

---

## 7. Normalized Cost Model and SLO Evaluation Criteria

### Normalized Cost Units
Running $1\text{ capacity unit}$ in the `ACTIVE` state for $1\text{ hour}$ ($3,600\text{ s}$) equals **$1.0\text{ cost unit}$**:

$$\text{Cost}_{\text{total}} = \int_{0}^{T_{\text{elapsed}}} \frac{r_{\text{active}} C_{\text{active}}(t) + r_{\text{prov}} C_{\text{prov}}(t) + r_{\text{standby}} C_{\text{standby}}(t)}{3600}\,dt$$

- **Active & Draining capacity** ($r_{\text{active}} = 1.00\text{ unit/cap-hr}$): Charged for all `ACTIVE` and busy `DRAINING` instances, plus the pre-upgrade capacity of a server undergoing a vertical upgrade.
- **Provisioning overhead** ($r_{\text{prov}} = 1.00\text{ unit/cap-hr}$): Charged for `BOOTING` instances during horizontal cold start ($10\text{ s}$) or warm resume ($2\text{ s}$), and for the incremental capacity delta $\Delta c = c_{\text{new}} - c_{\text{old}}$ during a $5\text{ s}$ vertical upgrade.
- **Warm standby capacity** ($r_{\text{standby}} = 0.25\text{ unit/cap-hr}$): Charged for idle `STANDBY` servers ($25\%$ of active rate).

### SLO Compliance Definitions
We evaluate two response-time thresholds—the **default SLO ($\text{P95} \le 1.0\text{ s}$)** and a **strict latency regime ($\text{P95} \le 0.35\text{ s}$)**—and explicitly distinguish two compliance criteria across the $N = 10$ seeds:
1. **Strict Per-Run Compliance (`10/10` runs, 100%):** Every individual simulation seed $i \in \{42..51\}$ satisfies $\text{P95}_i \le \text{SLO}$ with zero unfinished requests.
2. **Mean-P95 Feasibility:** The average P95 across seeds satisfies $\overline{\text{P95}} \le \text{SLO}$, reported alongside the exact per-run pass count ($k/10$) and pass percentage.

---

## 8. Installation, Testing, and Execution Commands

### 1. Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Automated Pytest Suite (27 Tests)
```bash
.venv/bin/pytest -v
```

### 3. Run Simulation Modes
```bash
# Single-seed baseline table (Seed 42)
.venv/bin/python main.py --mode baseline

# Run all 5 multi-seed experiments (N=10 seeds: 42..51) and save CSVs to results/
.venv/bin/python main.py --mode experiments --num-seeds 10

# Generate all 10 figures (300 DPI PNGs) in figures/
.venv/bin/python main.py --mode plots

# Run complete pipeline (experiments + plots)
.venv/bin/python main.py --mode all --num-seeds 10
```

---

## 9. Experimental Results and Statistical Analysis ($N = 10$ Seeds, `42..51`)

### Experiment 1: Strategy Comparison on `variable_baseline` ($\approx 23,271\text{ requests/run}$)

| Strategy | Config | Avg RT (s) | P50 RT (s) | P95 RT (s) | Max Seed P95 (s) | Avg Util. | Total Cost (units) | Cost / 1k Req | Default SLO ($\le 1.0\text{ s}$) | Strict SLO ($\le 0.35\text{ s}$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `static_1` | $1\times 1$ | $199.83 \pm 6.04$ | $168.26$ | $499.19 \pm 10.49$ | $528.94$ | $83.9\%$ | $1.0015 \pm 0.0021$ | $0.04304$ | $0/10$ ($0\%$) | $0/10$ ($0\%$) |
| `static_2` | $1\times 2$ | $2.3865 \pm 0.1919$ | $0.1042$ | $21.43 \pm 1.63$ | $25.06$ | $42.0\%$ | $2.0000 \pm 0.0000$ | $0.08595$ | $0/10$ ($0\%$) | $0/10$ ($0\%$) |
| `static_4` | $1\times 4$ | $0.0462 \pm 0.0006$ | $0.0375$ | $0.1212 \pm 0.0019$ | $0.1246$ | $21.0\%$ | $4.0000 \pm 0.0000$ | $0.17189$ | $10/10$ ($100\%$) | $10/10$ ($100\%$) |
| `horizontal` | $1..4\times 1$ | $0.1629 \pm 0.0022$ | $0.1500$ | $0.3907 \pm 0.0065$ | $0.4116$ | $42.7\%$ | **$1.9789 \pm 0.0242$** | **$0.08504$** | **$10/10$ ($100\%$)** | $0/10$ ($0\%$) |
| `hybrid_adaptive` | $[1]..[2,2]$ | $0.1191 \pm 0.0038$ | $0.0750$ | $0.3467 \pm 0.0051$ | $0.3500$ | $42.0\%$ | $2.0110 \pm 0.0560$ | $0.08642$ | $10/10$ ($100\%$) | $8/10$ ($80\%$) |
| `hybrid` | $1\times 1..2\times 2$ | $0.1090 \pm 0.0010$ | $0.0750$ | $0.3321 \pm 0.0056$ | $0.3469$ | $39.9\%$ | $2.1160 \pm 0.0122$ | $0.09093$ | $10/10$ ($100\%$) | **$10/10$ ($100\%$)** |
| `vertical` | $1\times 1..4$ | **$0.0982 \pm 0.0012$** | **$0.0717$** | **$0.3256 \pm 0.0060$** | **$0.3405$** | $39.7\%$ | $2.1229 \pm 0.0111$ | $0.09123$ | $10/10$ ($100\%$) | **$10/10$ ($100\%$)** |

*(Values show sample mean $\pm 95\%$ confidence interval half-width across $N = 10$ seeds.)*

### Paired Statistical Comparisons (`results/exp5_paired_comparisons.csv`)

Using identical seeds and cloned workloads across strategies, paired seed-by-seed differences ($d_i = x_{A,i} - x_{B,i}$, $t_{0.975, 9} = 2.262$) show which differences are statistically conclusive and which include zero within their $95\%$ CI:

| Scenario | Comparison ($A - B$) | Metric | Mean Paired Diff ($\bar{d}$) | Std ($s_d$) | 95% CI of Diff | Rel. Diff | 95% CI Includes Zero? |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `variable_baseline` | `horizontal - vertical` | Total Cost | $-0.14402$ | $0.04045$ | $[-0.17296, -0.11508]$ | $-6.78\%$ | **No (Significant)** |
| `variable_baseline` | `horizontal - hybrid` | Total Cost | $-0.13708$ | $0.04148$ | $[-0.16675, -0.10740]$ | $-6.48\%$ | **No (Significant)** |
| `variable_baseline` | `horizontal - hybrid_adaptive` | Total Cost | $-0.03208$ | $0.05724$ | $[-0.07303, +0.00887]$ | $-1.60\%$ | **Yes (Uncertain)** |
| `variable_baseline` | `hybrid_adaptive - hybrid` | Total Cost | $-0.10500$ | $0.08109$ | $[-0.16300, -0.04699]$ | $-4.96\%$ | **No (Significant)** |
| `variable_baseline` | `hybrid - vertical` | Total Cost | $-0.00694$ | $0.01074$ | $[-0.01462, +0.00074]$ | $-0.33\%$ | **Yes (Uncertain)** |
| `variable_baseline` | `horizontal - vertical` | P95 RT (s) | $+0.06509$ | $0.01354$ | $[+0.05541, +0.07478]$ | $+19.99\%$ | **No (Significant)** |
| `sudden_spike` | `hybrid - horizontal` | Total Cost | $-0.02582$ | $0.02100$ | $[-0.04084, -0.01079]$ | $-1.40\%$ | **No (Significant)** |
| `sudden_spike` | `vertical - horizontal` | Total Cost | $-0.02221$ | $0.02349$ | $[-0.03901, -0.00541]$ | $-1.20\%$ | **No (Significant)** |
| `sudden_spike` | `hybrid - vertical` | Total Cost | $-0.00361$ | $0.00668$ | $[-0.00839, +0.00117]$ | $-0.20\%$ | **Yes (Uncertain)** |
| `sudden_spike` | `hybrid - horizontal` | P95 RT (s) | $-0.11100$ | $0.02829$ | $[-0.13124, -0.09077]$ | $-22.71\%$ | **No (Significant)** |
| `recurring_spikes` | `horizontal - vertical` | Total Cost | $-0.00848$ | $0.03526$ | $[-0.03371, +0.01674]$ | $-0.35\%$ | **Yes (Uncertain)** |

### Key Conclusions for RQ1, RQ2, and RQ3

1. **RQ1 (Lowest Cost Under Default SLO $\text{P95} \le 1.0\text{ s}$):**
   - On `variable_baseline`, **Horizontal scaling (`horizontal`) achieves the lowest mean operating cost ($1.9789 \pm 0.0242\text{ units}$, $10/10$ runs compliant)**, which is statistically significantly lower than both `vertical` ($-6.78\%$, paired 95% CI $[-0.1730, -0.1151]$) and 3-tier `hybrid` ($-6.48\%$, paired 95% CI $[-0.1668, -0.1074]$).
   - **Mechanism:** During the 10-minute High-load phase (`1500–2100 s`, $\lambda = 12\text{ req/s}$, mean demand $1.56\text{ units}$), `horizontal` provisions $3\text{ units}$ ($3\times 1$), whereas binary-stepped `vertical` ($1 \to 2 \to 4$) and 3-tier `hybrid` ($1\times 1 \to 1\times 2 \to 2\times 2$) step up to $4\text{ units}$. When `hybrid_adaptive` adds an intermediate 3-unit state ($[2, 1]$), its cost drops to $2.0110\text{ units}$, whose paired difference against `horizontal` ($-0.0321$, 95% CI $[-0.0730, +0.0089]$) is not statistically distinguishable from zero.

2. **RQ2 (Startup Delays, Warm Standby, and Delayed Shutdown):**
   - **Startup Delays (`exp2`):** On `sudden_spike` ($6 \to 20\text{ req/s}$), cold-start delays of $20\text{ s}$ and $30\text{ s}$ cause `horizontal` P95 latency to reach $1.1491 \pm 0.3125\text{ s}$ ($6/10$ runs pass) and $3.7795 \pm 1.1583\text{ s}$ ($0/10$ runs pass) due to sequential $2 \to 3 \to 4$ instance boots. `vertical` ($\text{P95} = 0.9011\text{ s}$, $8/10$ pass at $30\text{ s}$) and `hybrid` ($\text{P95} = 0.8991\text{ s}$, $8/10$ pass at $30\text{ s}$) jump directly from $2 \to 4\text{ units}$ in one step.
   - **Warm Standby (`exp3`):** Under `recurring_spikes` with aggressive scale-down ($\text{SD}=30\text{ s}$, cold start $15\text{ s}$), enabling warm standby ($2\text{ s}$ resume at $25\%$ cost) reduces `horizontal` P95 latency by **$79.4\%$** ($2.5955\text{ s} \to 0.5334\text{ s}$, restoring $10/10$ SLO compliance, paired diff $-2.0621 \pm 0.2639\text{ s}$) and `hybrid` P95 by **$66.9\%$** ($6.4813\text{ s} \to 2.1444\text{ s}$) at an added cost of $+12.1\%$ and $+11.0\%$. On `variable_baseline`, warm standby adds $+8.6\%$ to $+10.7\%$ cost with $0.0\%$ latency change.
   - **Shutdown Delay (`exp4`):** Under `recurring_spikes` (standby off), a $30\text{ s}$ scale-down window triggers premature scale-down during $45\text{ s}$ lulls, causing SLO failures across all strategies (`vertical` $3.25\text{ s}$, `horizontal` $1.36\text{ s}$, `hybrid` $5.13\text{ s}$). Extending the window to **$60\text{ s}$** bridges the $45\text{ s}$ lulls and restores $10/10$ SLO compliance across all strategies ($\text{P95} = 0.38–0.52\text{ s}$) for $+4.0\%$ to $+6.3\%$ cost.

3. **RQ3 (Conditions Where Hybrid Scaling Offers an Advantage):**
   - **Strict Tail-Latency Requirement ($\text{P95} \le 0.35\text{ s}$ on `variable_baseline`):** Pure `horizontal` fails in **all 10 runs (`0/10`)** ($\overline{\text{P95}} = 0.3907\text{ s}$) because a capacity-1 server requires $0.35\text{ s}$ just to process a Heavy job ($0.35\text{ CPU-s}$). Under a **mean-P95 criterion** ($\overline{\text{P95}} \le 0.35\text{ s}$) or **$80\%$ per-run compliance ($8/10$ runs)**, `hybrid_adaptive` ($2.0110\text{ units}$, $\overline{\text{P95}} = 0.3467\text{ s}$) is the lowest-cost qualifying strategy, statistically significantly cheaper than both `hybrid` ($-4.96\%$) and `vertical` ($-5.27\%$). Under a **strict 100% per-run reliability requirement ($10/10$ runs)**, only `hybrid` ($2.1160\text{ units}$, $\max\text{P95} = 0.3469\text{ s}$) and `vertical` ($2.1229\text{ units}$, $\max\text{P95} = 0.3405\text{ s}$) qualify; `hybrid` has a slightly lower observed mean cost ($-0.00694\text{ units}$), though their paired 95% CI ($[-0.01462, +0.00074]$) includes zero.
   - **Sudden Isolated Traffic Spikes (`sudden_spike`):** Both `hybrid` ($1.8185\text{ units}$) and `vertical` ($1.8221\text{ units}$) are statistically significantly cheaper and faster than `horizontal` ($1.8443\text{ units}$, paired cost diff $-0.0258\text{ units}$, 95% CI $[-0.0408, -0.0108]$; P95 diff $-0.1110\text{ s}$) because `horizontal` must step down through an intermediate 3-server state after the spike. Between `hybrid` and `vertical`, `hybrid` has a slightly lower observed mean cost ($-0.00361\text{ units}$, $-0.20\%$), but the paired 95% CI ($[-0.00839, +0.00117]$) includes zero.
   - **Per-Instance Vertical Capacity Ceiling ($c_{\max,\text{node}} = 2$):** When single-server capacity cannot exceed $2\text{ units}$, `vertical` is equivalent to `static_2` ($\text{P95} = 21.43\text{ s}$, $0/10$ SLO compliance), leaving `hybrid` ($2\times 2$) and `hybrid_adaptive` as the only strategies capable of reaching $4\text{ units}$ of peak capacity while providing $2\times$ single-job speedup.

---

## 10. Key Modeling Assumptions and Limitations

1. **Non-Preemptive FIFO Execution:** Each server executes one request at a time in FIFO order ($t_s = W/c$).
2. **In-Place Live Vertical Resizing:** Vertical upgrades apply after a $5.0\text{ s}$ delay without rebooting or dropping an in-flight request. Legacy VM environments requiring full OS reboots for vertical resizing would experience downtime and higher tail latency.
3. **Idealized Linear Speedup and Cost:** Both service rate ($W/c$) and active cost rate scale linearly with $c \in \{1, 2, 4\}$. Sub-linear multi-core speedup ($t_s > W/c$ at $c=4$) would reduce the latency advantage of `vertical` ($1\times 4$) relative to `hybrid` ($2\times 2$).
4. **Synthetic Piecewise-Poisson Workloads:** Workloads are generated via a seeded piecewise-constant Poisson process for exact repeatability. Google Cluster Workload Traces are discussed in the report background as cluster utilization context rather than direct HTTP web request logs.

---

## 11. Generated Figures and Project Structure

All 10 figures in `figures/` are generated deterministically from the CSV datasets in `results/`:

- `figures/fig01_workload_over_time.png` — Request arrival rate and empirical throughput over time (`variable_baseline`).
- `figures/fig02_avg_response_time_by_strategy.png` — Mean response time across strategies ($N=10$ seeds, $\pm 95\%$ CI).
- `figures/fig03_p95_response_time_by_strategy.png` — 95th-percentile (P95) response time against default ($1.0\text{ s}$) and strict ($0.35\text{ s}$) SLO thresholds.
- `figures/fig04_total_cost_by_strategy.png` — Normalized operating cost breakdown (active, provisioning, standby).
- `figures/fig05_active_servers_over_time.png` — Active instance count trajectories over time.
- `figures/fig06_available_capacity_over_time.png` — Total active processing capacity trajectories vs. workload demand.
- `figures/fig07_queue_length_over_time.png` — FIFO waiting queue length trajectories during traffic surges.
- `figures/fig08_cost_vs_response_time_tradeoff.png` — Cost vs. P95 latency Pareto trade-off frontier.
- `figures/fig09_cold_start_impact.png` — Provisioning startup delay sensitivity ($0\text{–}30\text{ s}$) on `variable_baseline` and `sudden_spike`.
- `figures/fig10_standby_and_shutdown_sensitivity.png` — Warm standby mitigation and shutdown observation window sensitivity ($30\text{–}120\text{ s}$) on `recurring_spikes`.

### Repository Layout
```text
Project-DTA400/
├── config.py                # Simulation parameters, request classes, cost rates, and scenario definitions
├── workload.py              # Seeded non-homogeneous Poisson workload generator & Common Random Numbers cloning
├── server.py                # FIFO RequestQueue, ServerInstance state machine, and ServerPool
├── scaling.py               # Static baselines and Vertical, Horizontal, Hybrid, & Adaptive Hybrid autoscalers
├── metrics.py               # Continuous-time capacity/cost integrator and SLO evaluator
├── experiments.py           # Multi-seed experiment runner (Experiments 1–5) and paired statistical tests
├── plots.py                 # Matplotlib figure generator (fig01–fig10)
├── main.py                  # CLI entry point (--mode baseline | experiments | plots | all)
├── requirements.txt         # Pinned Python dependencies
├── pytest.ini               # Pytest configuration
├── tests/                   # 27 automated unit and integration tests
├── results/                 # Verified CSV datasets from Experiments 1–5 (N=10 seeds)
├── figures/                 # 10 publication-quality figures (300 DPI PNG)
└── report/                  # IEEE conference paper (.md, .docx, .pdf), outline, and presentation guide
```

---

## 12. Reproducibility and Repository Link

- **Deterministic Reproducibility:** All stochastic experiments use explicit seed sequences (`42..51`) and Common Random Numbers (`clone_workload`), guaranteeing that re-running `python main.py --mode all --num-seeds 10` reproduces all CSV datasets in `results/` and figures in `figures/`.
- **Public GitHub Repository:** [https://github.com/SAS2005/Project-DTA400](https://github.com/SAS2005/Project-DTA400) (`https://github.com/SAS2005/Project-DTA400.git`)
