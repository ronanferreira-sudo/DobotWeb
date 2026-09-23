import markdown
import re
from fpdf import FPDF

with open('MANUAL_USUARIO.md', encoding='utf-8') as f:
    texto = f.read()

# Clean up excessive newlines
texto = re.sub(r'\n{3,}', '\n\n', texto)

html = markdown.markdown(texto, extensions=['tables', 'fenced_code', 'extra'])

# fpdf write_html has limited HTML support - strip all formatting tags inside td
html = re.sub(r'<td>(.*?)</td>', lambda m: '<td>' + re.sub(r'<[^>]+>', '', m.group(1)) + '</td>', html, flags=re.DOTALL)

pdf = FPDF()
pdf.add_font('Arial', '', 'C:/Windows/Fonts/arial.ttf')
pdf.add_font('Arial', 'B', 'C:/Windows/Fonts/arialbd.ttf')
pdf.add_font('Arial', 'I', 'C:/Windows/Fonts/ariali.ttf')

# ---------- Cover page ----------
pdf.add_page()
pdf.set_text_color(37, 99, 235)
pdf.set_font('Arial', 'B', 26)
pdf.cell(0, 25, 'Manual do Usuario', align='C', new_x='LMARGIN', new_y='NEXT')
pdf.ln(4)
pdf.set_font('Arial', 'B', 18)
pdf.cell(0, 15, 'Controle Dobot', align='C', new_x='LMARGIN', new_y='NEXT')
pdf.ln(10)
pdf.set_font('Arial', '', 11)
pdf.set_text_color(100, 100, 100)
pdf.multi_cell(0, 5, 'Guia rapido para operar o braco robotico Dobot Magician Lite sem ser administrador do sistema.', align='C')
pdf.ln(15)
pdf.set_font('Arial', 'B', 12)
pdf.set_text_color(0, 0, 0)
pdf.cell(0, 10, 'Acesso Nao-Admin (via IP de rede)', align='C', new_x='LMARGIN', new_y='NEXT')

# ---------- Content pages ----------
pdf.add_page()
pdf.set_text_color(51, 51, 51)
pdf.set_font('Arial', size=10)
pdf.write_html(html)
pdf.output('MANUAL_USUARIO.pdf')
print('PDF regenerated')
