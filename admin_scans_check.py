import os, sys, django
sys.path.insert(0, r'C:\Users\Latitude E5450\Desktop\OWERU TECH_SOLUTION')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'oweru_tech_solutions.settings')
django.setup()
from django.test import Client
from core.models import User, Scan

sec = Client()
admin = User.objects.filter(role='admin').first()
sec.force_login(admin)
scan = Scan.objects.exclude(findings=[]).first()

print('probe :', scan.id, scan.website_url, '| score', scan.score, '| findings', len(scan.findings or []))

for name, path in [
    ('scans list ', '/admin-app/scans/'),
    ('scan detail', f'/admin-app/scans/{scan.id}/'),
]:
    r = sec.get(path)
    h = r.content.decode()
    print(f'  {name}: {r.status_code} | has url={scan.website_url in h} | has score={str(scan.score) in h} | has finding={any(f.get("description","")[:30] in h for f in (scan.findings or []))}')
