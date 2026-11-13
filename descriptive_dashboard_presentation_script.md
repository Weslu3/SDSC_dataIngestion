# St. Dominic Savio College (SDSC) — Descriptive Dashboard Presentation Script
**Oral Defense & Executive Walkthrough Talk Track**  
**Focus:** Historical Baseline, Demographic Profile, Geospatial Feeder Analysis, and Student Retention

---

## Presentation Metadata & Timing Guide
- **Target Audience:** Capstone Defense Panel / SDSC Board of Trustees / Academic Deans & Registrar
- **Estimated Duration:** 10 to 12 minutes (including dashboard walkthrough)
- **Visual Companion:** Streamlit Analytics Web Application (`Dashboard -> Descriptive History`) / `SDSC_Descriptive_v2.pbix`
- **Presenters:** Capstone Research Team

---

## Slide 1 / Overview: Introduction to Descriptive Analytics

### Speaker Talk Track:
> "Good morning, esteemed members of the panel, our research adviser, and academic administrators. 
> 
> Today, we are proud to present the findings from the **Descriptive Analytics Layer** of our St. Dominic Savio College Enrollment Planning and Analytics System. 
> 
> In institutional decision-making, you cannot forecast the future or prescribe optimal quotas without first understanding the bedrock of your institution: **where we have been, who our students are, where they travel from, and why they stay.**
> 
> Our descriptive dashboard consolidates data across four core analytical dimensions:
> 1. **Enrollment Over Time:** Historical headcount trajectories and the balance between fresh admissions and returning student retention.
> 2. **Student Profile:** Demographic composition across year levels, gender distribution, and the primary drivers influencing enrollment choice.
> 3. **Where Students Live:** Geospatial concentration, primary feeder barangays, and the mathematical distance-decay effect.
> 4. **Satisfaction and Retention:** Institutional satisfaction metrics across seven campus dimensions and their direct correlation with cohort persistence.
> 
> Let us step directly into Sub-Page 1 to evaluate our historical enrollment trajectory."

---

## Sub-Page 1: Enrollment Over Time

### Dashboard Display:
- **KPI Cards:** Latest 1st Semester Headcount: **429** | New Freshmen: **85** | New Student Share: **19.8%**
- **Chart 1:** New vs. Returning Students (Stacked Bar Chart, AY 2020-2021 to Latest)
- **Chart 2:** This Year vs. Same Semester Last Year (Dual-Axis Headcount Bar + YoY Growth Rate Line)

### Speaker Talk Track:
> "Looking at our first dashboard view, **Enrollment Over Time**, we analyze SDSC's post-pandemic recovery and stability pattern.
> 
> In the top KPI cards, our baseline latest 1st Semester headcount stands at **429 students**, with **85 newly enrolled freshmen**, representing a **19.8% new intake share**. 
> 
> When we examine the historical trend bar chart on the left, you will observe three distinct phases in SDSC's enrollment lifecycle:
> 
> 1. **The Pandemic Compression (AY 2020-2021 to 2021-2022):** Enrollment was severely constrained during the height of lockdowns, bottoming at 129 to 131 students, driven primarily by economic uncertainty and remote learning friction.
> 2. **The Rebound Surge (AY 2022-2023):** With the reopening of face-to-face instruction, SDSC experienced a sharp recovery surge of **+272.1%**, reaching 480 students. As the green stack illustrates, 381 of these students were new intake, demonstrating significant pent-up demand for physical college instruction.
> 3. **The Current Consolidation Phase (AY 2023-2024 to 2025-2026):** Over the past three academic years, enrollment has stabilized between 429 and 455 students, with marginal contractions averaging only -2% to -3% year-over-year.
> 
> Crucially, as shown by the indigo bars in our stacked column visualization, **returning students now comprise over 80% of total headcount**. While institutional stability is currently sustained by strong retention, this highlights a key strategic insight: **SDSC must aggressively revitalize top-of-funnel freshman recruitment to expand total college capacity.**"

---

## Sub-Page 2: Student Profile (Demographics & Decision Drivers)

### Dashboard Display:
- **KPI Cards:** Profiled Enrollment Cohort: **1,546 Students** | Leading Decision Factor: **Location / Proximity (35.3%)**
- **Chart 1:** Who Our Students Are (Horizontal Bar Chart grouped by Gender and Year Level)
- **Chart 2:** Main Reason for Choosing SDSC (Horizontal Bar Chart from Student Satisfaction Survey)

### Speaker Talk Track:
> "Moving to our second tab, **Student Profile**, we examine the demographic composition and behavioral motivations of our 1,546 profiled students.
> 
> First, regarding gender balance: SDSC maintains near-perfect parity, with **50.9% male students (789 students)** and **49.1% female students (760 students)**. This balanced distribution indicates that SDSC's program portfolio—spanning Nursing, Criminology, Business, and Computer Studies—appeals equally across demographic segments without institutional gender skew.
> 
> Second, looking at Year Level distribution:
> - **1st Year:** 34.7% (1,723 records across multi-year cohorts)
> - **2nd Year:** 23.8% (1,183 records)
> - **3rd Year:** 25.0% (1,244 records)
> - **4th Year:** 15.9% (789 records)
> 
> The sharpest takeaway on this page lies in the chart to your right: **Main Reason for Choosing SDSC**, derived from our Student Satisfaction Survey.
> 
> When incoming students were asked what primarily drove their choice of SDSC:
> - **35.3% cited Location and Proximity** as their number one deciding factor.
> - **18.5% cited Academic Reputation.**
> - **17.6% cited Program Availability.**
> - Together, these top three factors account for **over 71% of all student decisions**.
> 
> Factors like Affordability (5.9%) and Personal Recommendations (6.4%) rank notably lower. This proves empirically that SDSC operates as a community anchor institution. Students choose us primarily because we provide accredited degree programs directly accessible to their homes."

---

## Sub-Page 3: Where Students Live (Geospatial Feeder Analysis)

### Dashboard Display:
- **KPI Cards:** Students Within 5 km: **55.8%** | Spearman rho Correlation: **-0.67** | Distance Impact: **Strong Inverse Yield (p < 0.001)**
- **Chart 1:** Students by Distance from Campus (Grouped Distance Bands: <2 km, 2-5 km, 5-10 km, >10 km)
- **Chart 2:** Top Barangays of Residence (Horizontal Ranking with Student Headcount & Road Distance)

### Speaker Talk Track:
> "This brings us to Sub-Page 3, **Where Students Live**, which forms the empirical bridge between our descriptive and diagnostic research.
> 
> In the top KPI cards, our findings reveal a dramatic concentration:
> - **55.8% of all enrolled students reside within 5 kilometers of the SDSC campus.**
> - When we expand to a 10 km radius, that figure surges to **92.7%**.
> - Only **7.3% (233 students)** travel further than 10 kilometers.
> 
> Statistically, our diagnostic engine computed a **Spearman rank correlation coefficient of -0.67 (p < 0.001)**. In quantitative terms, this confirms a statistically significant, strong inverse relationship: as geographic distance from the SDSC campus increases, enrollment yield decays rapidly.
> 
> Now, examine the bar chart on the right: **Top Barangays of Residence**.
> 
> Our top feeder communities are heavily concentrated along the North Caloocan and Quirino Highway corridors:
> 1. **Barangay 176-A (Bagong Silang):** Represents our largest single feeder community with **733 enrolled students** (at 4.95 km distance, yield of 171.8 per 1,000 age-eligible youth).
> 2. **Barangay 173:** Second with **397 students** (5.58 km, with our highest density yield of 288.8 per 1,000).
> 3. **Barangay 186:** Third with **212 students** (1.95 km).
> 4. **Barangay 181:** Fourth with **191 students** (just 0.63 km from campus).
> 5. Followed by Barangays 179, 177, 171, 185, 184, and Novaliches Proper in Quezon City.
> 
> **Strategic Takeaway for the Administration:** Marketing budget and senior high school career orientation caravans should not be dispersed uniformly across the entire National Capital Region. Over half our enrollment comes from a 5-kilometer perimeter; concentrating outreach campaigns in Barangays 176-A, 173, and 186 will generate the highest return on recruitment expenditure."

---

## Sub-Page 4: Satisfaction and Retention

### Dashboard Display:
- **KPI Cards:** Average Satisfaction: **3.65 / 5.0** | Would Recommend SDSC: **65.8%** | Average Cohort Retention: **85.1%**
- **Chart 1:** How Students Rate SDSC (Weighted Average Rating across 7 Dimensions)
- **Chart 2:** Students Who Stayed to the Next Year (Cohort Retention Rates by Academic Transition)

### Speaker Talk Track:
> "Finally, let us direct our attention to Sub-Page 4: **Satisfaction & Retention**, measuring institutional service quality and student persistence.
> 
> Across all seven evaluation dimensions in our Student Satisfaction Survey, SDSC achieves an overall average score of **3.65 out of 5.0**, reflecting solid positive institutional satisfaction:
> 
> Ranking our institutional dimensions from highest to lowest:
> - **Campus Cleanliness:** Ranks #1 at **3.70 / 5.0**.
> - **Campus Safety:** Ranks #2 at **3.66 / 5.0**.
> - **Campus Canteen:** Ranks #3 at **3.66 / 5.0**.
> - **Teaching Quality:** Ranks #4 at **3.66 / 5.0**.
> - **Student Interaction:** Ranks #5 at **3.63 / 5.0**.
> - **Campus Facilities:** Ranks #6 at **3.63 / 5.0**.
> - **Staff Professionalism:** Ranks #7 at **3.63 / 5.0**.
> 
> Furthermore, **65.8% of surveyed students affirm that they would actively recommend SDSC** to prospective enrollees, demonstrating healthy organic advocacy.
> 
> Now observe the retention chart on your right: **Students Who Stayed to the Next Year**.
> 
> We measured cohort persistence across successive academic years:
> - Transitioning from **AY 2023-2024 to AY 2024-2025**, cohort retention stood at **67.7%** (308 of 455 students retained).
> - However, transitioning from **AY 2024-2025 to AY 2025-2026**, cohort retention jumped to **91.2%** (394 of 432 students retained).
> 
> This represents a remarkable **23.5 percentage point improvement in institutional retention**. It proves that once students navigate their transition into SDSC, academic continuity and program satisfaction remain exceptionally strong."

---

## Conclusion & Summary Recommendations

### Speaker Talk Track:
> "To synthesize the findings of our Descriptive Dashboard into actionable institutional intelligence:
> 
> 1. **Baseline Health:** Enrollment has settled at a stable operational baseline (~430 to 450 students), sustained by high returning cohort retention (91.2%).
> 2. **Catchment Focus:** 55.8% of students live within 5 km, and 92.7% live within 10 km. Distance is an active barrier (Spearman rho = -0.67); proximity is the primary selling proposition (35.3%).
> 3. **Actionable Priority:** Outreach and transportation initiatives targeted specifically at Barangays 176-A, 173, and 186 will directly boost new intake share beyond its current 19.8% baseline.
> 
> This descriptive baseline serves as the quantitative foundation upon which our diagnostic correlations, predictive Holt/OLS forecasts, and prescriptive TOPSIS quotas operate.
> 
> Thank you very much, and we are now ready to answer any questions from the panel."

---

## Anticipated Panel Questions & Prepared Answers

### Q1: Why is new student intake only 19.8% while returning retention is over 80%?
> **Answer:** "During the post-COVID transition, SDSC prioritized re-enrolling and graduating paused cohorts. While high retention is commendable and maintains tuition revenue stability, a healthy long-term enrollment pyramid requires freshman intake of 30% to 35%. Our prescriptive layer specifically addresses this by allocating quotas to high-yield feeder barangays."

### Q2: What does the -0.67 Spearman correlation actually tell the administration?
> **Answer:** "It demonstrates mathematically that student yield decays rapidly with road distance. Because public transit routes along Quirino Highway and Zabarte Road involve transfer costs and traffic bottlenecks, prospective students residing beyond 7 km gravitate to competitor schools in Fairview or SJDM. SDSC should prioritize institutional shuttles or targeted feeder senior high school partnerships within the 5 km radius."

### Q3: Why did retention jump from 67.7% to 91.2% between the two observed cohort transitions?
> **Answer:** "The 2023-2024 to 2024-2025 transition captured the tail-end of irregular student dropouts following the pandemic return-to-school shock. By 2024-2025, curricula had normalized, faculty advising improved, and hybrid scheduling stabilized student persistence, resulting in the 91.2% retention benchmark."

