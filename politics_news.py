from fpdf import FPDF

pdf = FPDF()
pdf.add_page()
pdf.set_font("Arial", "B", 16)
pdf.cell(0, 10, "Recent Politics News - March 2026", ln=True, align="C")
pdf.ln(10)

pdf.set_font("Arial", "B", 14)
pdf.cell(0, 10, "Trump Administration:", ln=True)
pdf.set_font("Arial", "", 12)
pdf.multi_cell(0, 8, "- Intelligence chiefs testified they don't take Putin at his word (contrasting with Special Envoy Witkoff's comments)")
pdf.multi_cell(0, 8, "- Markwayne Mullin had a confirmation hearing for Homeland Security leadership")
pdf.multi_cell(0, 8, "- Senate Republicans blocked Democrats' war powers resolution on Iran")
pdf.ln(5)

pdf.set_font("Arial", "B", 14)
pdf.cell(0, 10, "Other Headlines:", ln=True)
pdf.set_font("Arial", "", 12)
pdf.multi_cell(0, 8, "- Gavin Newsom criticized climate rollbacks: 'They want to make pollution great again'")
pdf.multi_cell(0, 8, "- China watching US politics closely after summit delay, seeking leverage")
pdf.multi_cell(0, 8, "- Pennsylvania voters at gas stations show midterm concerns")
pdf.multi_cell(0, 8, "- DOJ says Paramount-Warner Bros deal review isn't political")
pdf.multi_cell(0, 8, "- Drones detected over base where Rubio and Hegseth live")

pdf.output("politics_news.pdf")
print("PDF created: politics_news.pdf")
