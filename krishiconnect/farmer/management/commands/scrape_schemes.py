import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from farmer.models import GovernmentScheme

class Command(BaseCommand):
    help = 'Scrapes agricultural government schemes from a public portal'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all existing schemes before scraping',
        )

    def handle(self, *args, **kwargs):
        if kwargs.get('clear'):
            self.stdout.write("Wiping out old government schemes...")
            count, _ = GovernmentScheme.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'Successfully deleted {count} existing schemes.'))

        self.stdout.write("Loading detailed mock schemes for demonstration...")
        mock_schemes = [
            {
                'title': 'Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)',
                'description': 'Under the Scheme an income support of Rs.6000/- per year is provided to all farmer families across the country in three equal installments.',
                'link': 'https://pmkisan.gov.in/',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'All landholding farmers families, which have cultivable landholding in their names.',
                'related_documents': 'Aadhaar Card, Bank Account Details, Land Ownership Records.'
            },
            {
                'title': 'Pradhan Mantri Fasal Bima Yojana (PMFBY)',
                'description': 'Provides a comprehensive insurance cover against failure of the crop. Available on myScheme portal.',
                'link': 'https://pmfby.gov.in/',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'All farmers growing notified crops in a notified area during the season who have insurable interest in the crop.',
                'related_documents': 'Land records, Bank Passbook, Aadhaar card, Sowing Certificate.'
            },
            {
                'title': 'Pradhan Mantri Krishi Sinchayee Yojana (PMKSY)',
                'description': 'Focuses on improving water use efficiency and expanding cultivable areas under assured irrigation (Per Drop More Crop). Listed on myScheme.gov.in.',
                'link': 'https://www.myscheme.gov.in/schemes/pmksy',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'Farmers with agricultural land and access to water resources for irrigation.',
                'related_documents': 'Aadhaar card, Land documents, Bank account details.'
            },
            {
                'title': 'Paramparagat Krishi Vikas Yojana (PKVY)',
                'description': 'An initiative to promote organic farming in the country, improving soil health and organic matter content.',
                'link': 'https://pgsindia-ncof.gov.in/pkvy/index.aspx',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'A group of 50 or more farmers with a total of 50 acres of land to take up organic farming.',
                'related_documents': 'Aadhaar card, Land records, Bank details, Group registration documents.'
            },
            {
                'title': 'National Agriculture Market (e-NAM)',
                'description': 'A pan-India electronic trading portal which networks the existing APMC mandis to create a unified national market for agricultural commodities.',
                'link': 'https://www.enam.gov.in/web/',
                'image_url': 'https://www.enam.gov.in/web/assets/images/enam_logo.png',
                'eligibility_criteria': 'Farmers, traders, and buyers registered with the respective APMC mandate.',
                'related_documents': 'Farmer/Trader registration ID, Bank account, Aadhaar card.'
            },
            {
                'title': 'Kisan Credit Card (KCC)',
                'description': 'Aims to provide adequate and timely credit support from the banking system to farmers for their cultivation and other needs.',
                'link': 'https://agricoop.nic.in/en/kisan-credit-card-kcc',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'All farmers-individuals/Joint borrowers who are owner cultivators. Tenant farmers, Oral lessees and Share Croppers.',
                'related_documents': 'Aadhaar card, PAN card, Land holding documents, Passport size photos.'
            },
            {
                'title': 'Agri Clinics & Agri Business Centres (ACABC)',
                'description': 'Available via JanSamarth portal. Aims to supplement agricultural extension by providing credit to setup agriventures.',
                'link': 'https://www.jansamarth.in/agri-clinics-and-agri-business-centres-scheme',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'Agriculture graduates/diploma holders.',
                'related_documents': 'Educational certificates, Project report, Bank loan application.'
            },
            {
                'title': 'Bhausaheb Fundkar Phalbag Lagwad Yojana',
                'description': 'Aims to promote horticulture by providing 100% subsidy for fruit orchard planting to farmers in Maharashtra under MahaDBT.',
                'link': 'https://mahadbt.maharashtra.gov.in/Farmer/Login/Login',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'Farmers in Maharashtra with minimum 0.20 ha and maximum 6.00 ha land.',
                'related_documents': 'Aadhaar card, 7/12 & 8A extract, Bank passbook, Soil testing report.'
            },
            {
                'title': 'Nanaji Deshmukh Krishi Sanjivani Yojana (PoCRA)',
                'description': 'A MahaDBT project to promote climate-resilient agriculture in drought-prone areas of Maharashtra.',
                'link': 'https://mahadbt.maharashtra.gov.in/',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'Small and marginal farmers in drought-prone villages of Maharashtra.',
                'related_documents': 'Aadhaar card, 7/12 extract, Bank account details, Caste certificate (if applicable).'
            },
            {
                'title': 'Magel Tyala Shet Tale',
                'description': 'A Maharashtra Aaple Sarkar initiative to provide a farm pond on demand to every farmer to ensure water availability for irrigation.',
                'link': 'https://aaplesarkar.mahaonline.gov.in/en/Login/Login',
                'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                'eligibility_criteria': 'Farmers in Maharashtra possessing at least 0.60 hectares of land.',
                'related_documents': '7/12 & 8A extract, Aadhaar card, Bank passbook, BPL certificate (if applicable).'
            }
        ]
        
        for ms in mock_schemes:
            GovernmentScheme.objects.update_or_create(
                title=ms['title'],
                defaults={
                    'description': ms['description'], 
                    'link': ms['link'],
                    'image_url': ms['image_url'],
                    'eligibility_criteria': ms.get('eligibility_criteria', ''),
                    'related_documents': ms.get('related_documents', '')
                }
            )
        self.stdout.write(self.style.SUCCESS(f'Successfully loaded {len(mock_schemes)} mock schemes!'))

        self.stdout.write("Fetching latest schemes...")
        
        # Target: India.gov.in agriculture section
        url = "https://www.india.gov.in/topics/agriculture"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            items = soup.find_all('div', class_='field-content')
            
            count = 0
            for item in items:
                link_tag = item.find('a')
                if link_tag:
                    title = link_tag.text.strip()
                    link = link_tag.get('href')
                    if link and link.startswith('/'):
                        link = "https://www.india.gov.in" + link
                        
                    scheme, created = GovernmentScheme.objects.get_or_create(
                        title=title,
                        defaults={
                            'description': 'Detailed information about this scheme is available on the official portal.', 
                            'link': link,
                            'image_url': 'https://upload.wikimedia.org/wikipedia/commons/e/eb/Emblem_of_India.svg',
                            'eligibility_criteria': 'Please check the official portal for detailed eligibility criteria.',
                            'related_documents': 'Please check the official portal for required documents.'
                        }
                    )
                    if created:
                        count += 1
                        
            self.stdout.write(self.style.SUCCESS(f'Successfully scraped and added {count} new schemes!'))
            
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.WARNING(f'Network/Connection error occurred: {str(e)}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error occurred while scraping: {str(e)}'))
