# IEEE Conference Paper Outline — DTA400 Network Simulation

**Target Format:** IEEE Conference Template (A4, Two-Column, 10-pt Times New Roman Body Text, 8-pt Tables/Captions/References, 4 pages maximum including references)  
**Author of Individual Paper:** Shucayb Said (Simulation & experiments developed jointly with Firat Kaya)  
**Title:** *Dynamic Server Scaling: Performance and Cost Trade-Offs of Vertical, Horizontal, and Hybrid Autoscaling Under Variable Workloads*  
**University:** Department of Engineering Science, University West (*Högskolan Väst*), Trollhättan, Sweden

---

## Page Budget & Section Allocation (4.0 A4 Pages at 10-pt Body Text)

| Section | Target Length | Key Contents & Visual Elements |
| :--- | :--- | :--- |
| **Title, Author Block (1-Column Header)** | ~0.18 page | 24-pt Paper Title, 11-pt Author Name, 10-pt Affiliation & Joint-Work Note |
| **Abstract & Keywords (2-Column Body Start)** | ~0.22 page | 9-pt Bold Structured Abstract (~185 words), 9-pt Bold/Italic Keywords |
| **I. Introduction** | ~0.40 page | Problem context, vertical/horizontal/hybrid paradigms, explicit **RQ1, RQ2, RQ3** |
| **II. Background and Related Work** | ~0.35 page | Cloud elasticity taxonomy, queuing theory ($M/G/1\text{-speed-}c$ vs. $M/G/k\text{-speed-}1$), cold starts, warm pooling, hysteresis |
| **III. Methodology and Simulation Design** | ~0.95 page | Five-component SimPy 4.1.2 architecture, job classes ($\mathbb{E}[W]=0.13\text{ CPU-s}$), post-horizon drain phase & throughput definitions, `Table I` (strategy topologies $1\times c$ vs. $k\times 1$), continuous-time normalized cost model, Common Random Numbers ($N=10$ seeds) |
| **IV. Experimental Results** | ~1.35 pages | **A. Baseline Strategy Comparison (RQ1):** `Table II`, `Fig. 1` (`fig03` P95 response time), `Fig. 2` (`fig08` Cost–P95 Pareto front).<br>**B. Cold-Start, Standby, and Shutdown Delay Sensitivity (RQ2):** `Fig. 3` (`fig09` startup delay $0\text{–}30\text{ s}$), `Fig. 4` (`fig10` warm standby and shutdown delay $30\text{–}120\text{ s}$).<br>**C. Multi-Scenario & Paired Statistical Comparison of Hybrid Regimes (RQ3):** `Table III` (paired differences $d_i$, 95% CI, statistical significance, and strict per-run vs. mean-P95 compliance). |
| **V. Discussion and Threats to Validity** | ~0.30 page | Step granularity vs. single-request speedup ($W/c$), paired CI interpretation, idealized speedup & synthetic workload limitations |
| **VI. Conclusion & References** | ~0.25 page | Empirical synthesis answering **RQ1, RQ2, and RQ3**, plus 10 IEEE references (`[1]`–`[10]`) at 8-pt |

---

## Selected Readable Figures & Tables in the 4-Page Paper

To ensure every figure and table is legible at IEEE standard font sizes (**10-pt body text, 8-pt tables and captions**) within the 4-page limit, the paper embeds **3 compact 4-to-6-column tables** and **4 high-impact figures** (while the repository retains all 10 figures `fig01`–`fig10`):

1. **Table I:** Scaling Strategy Configurations and Baseline Topologies ($1\times c$ vs. $k\times 1$).
2. **Table II:** Baseline Performance and Cost on `variable_baseline` ($N=10$ seeds, Mean $\pm 95\%$ CI, and Per-Run SLO Compliance at $1.0\text{ s}$ and $0.35\text{ s}$).
3. **Table III:** Paired Seed-by-Seed Statistical Comparisons ($d_i = x_{A,i} - x_{B,i}$, Mean Diff, 95% CI, Relative %, and Significance).
4. **Fig. 1 (`fig03_p95_response_time_by_strategy.png`):** P95 response time comparison across strategies on `variable_baseline`.
5. **Fig. 2 (`fig08_cost_vs_response_time_tradeoff.png`):** Operating Cost vs. P95 Response Time Pareto trade-off chart.
6. **Fig. 3 (`fig09_cold_start_impact.png`):** Effect of provisioning startup delay ($0\text{–}30\text{ s}$) on P95 latency under `variable_baseline` and `sudden_spike`.
7. **Fig. 4 (`fig10_standby_and_shutdown_sensitivity.png`):** Warm standby impact (Panel A) and scale-down observation delay sensitivity (Panel B) under `recurring_spikes`.
