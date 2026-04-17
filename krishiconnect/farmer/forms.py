import os
from django import forms
from .models import Product

def truncate_filename(filename, max_length=100):
    name, ext = os.path.splitext(filename)
    if len(filename) <= max_length:
        return filename
    allowed_length = max_length - len(ext)
    truncated_name = name[:allowed_length]
    return f"{truncated_name}{ext}"

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'category', 'price', 'stock', 'description', 'image']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Describe your produce...'}),
        }

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image:
            image.name = truncate_filename(image.name, max_length=100)
        return image
