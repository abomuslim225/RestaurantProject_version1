import random
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# code = random.randint(100000, 999999)


def send_email(receiver_email, code):
    sender_email = os.getenv('SENDER_EMAIL')
    password = os.getenv('EMAIL_PASSWORD')

    message = MIMEMultipart("alternative")
    message["Subject"] = "Restaurant kirish kodi"
    message["From"] = sender_email
    message["To"] = receiver_email

    html = f"""\
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#1b2838;font-family:Arial,sans-serif">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#1b2838;padding:40px 0">
      <tr><td align="center">
        <table width="500" cellpadding="0" cellspacing="0" style="background:#c6d4df;border-radius:4px;overflow:hidden">
    
          <tr><td style="background:#1b2838;padding:20px 28px">
            <span style="color:#ffffff;font-size:16px;font-weight:700;letter-spacing:0.5px">Restaurant name</span>
          </td></tr>
    
          <tr><td style="padding:28px;color:#1b2838">
            <p style="font-size:14px;font-weight:700;margin:0 0 12px">Salom,</p>
            <p style="font-size:13px;line-height:1.6;margin:0 0 20px;color:#3d3d3f">
              hisobingizga kirish uchun tasdiqlash kodi so'raldi. Quyidagi kodni kiriting:
            </p>
    
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr><td style="background:#1b2838;border-radius:4px;padding:18px;text-align:center">
                <p style="color:#8f98a0;font-size:11px;letter-spacing:1px;margin:0 0 8px;text-transform:uppercase">Kirish kodi</p>
                <p style="color:#ffffff;font-size:28px;font-weight:700;letter-spacing:6px;font-family:monospace;margin:0">{code}</p>
              </td></tr>
            </table>
    
            <p style="font-size:13px;line-height:1.6;margin:20px 0;color:#3d3d3f">
              Ushbu kod <strong>15 daqiqa</strong> davomida amal qiladi.
              Agar siz so'rov yubormagan bo'lsangiz, ushbu xabarni e'tiborsiz qoldiring.
            </p>
            <hr style="border:none;border-top:1px solid #8f98a0;opacity:0.4;margin:20px 0">
            <p style="font-size:11px;color:#3d3d3f;margin:0">
              Bu xabar Steam xavfsizlik tizimi tomonidan avtomatik yuborildi.
            </p>
          </td></tr>
    
          <tr><td style="background:#1b2838;padding:14px 28px;text-align:center">
            <span style="color:#8f98a0;font-size:11px">Steam &bull; Valve Corporation &bull; Bellevue, WA</span>
          </td></tr>
    
        </table>
      </td></tr>
    </table>
    </body>
    </html>
    """

    part2 = MIMEText(html, "html")
    message.attach(part2)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message.as_string())
