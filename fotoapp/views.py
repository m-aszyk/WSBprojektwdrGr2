# fotoapp/views.py

import os
import zipfile
import stripe
from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from django.urls import reverse
from django.core.mail import send_mail
from .models.session import Session
from .models.photo import Photo
from .utils import decrypt_path, encrypt_path
from .cart import (
    add as cart_add,
    remove as cart_remove,
    count as cart_count,
    _cart as get_cart
)

# Konfiguracja Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

# ===============================
#         STRONY GŁÓWNE
# ===============================

def homepage(request):
    return render(request, 'fotoapp/homepage.html')


def oferta(request):
    return render(request, 'fotoapp/oferta.html')


def kontakt(request):
    return render(request, 'fotoapp/kontakt.html')


def check_password(request):
    if request.method == "POST":
        password = request.POST.get('password')
        try:
            session = Session.objects.get(password=password)
            session.access_token = session.generate_new_token()
            session.save()
            return redirect('gallery_view', access_token=session.access_token)
        except Session.DoesNotExist:
            return render(request, 'fotoapp/homepage.html', {'error': 'Nieprawidłowe hasło'})
    return redirect('home')


# ===============================
#            GALERIA
# ===============================

def gallery_view(request, access_token):
    """
    Widok galerii zdjęć dla użytkownika z unikalnym tokenem dostępu.
    """
    session = get_object_or_404(Session, access_token=access_token)
    photos = session.photos.all()
    request.session['gallery_access'] = True
    for photo in photos:
        photo.token = encrypt_path(photo.image.name)
    return render(request, 'fotoapp/gallery.html', {'session': session, 'photos': photos})


def serve_encrypted_image(request, token):
    """
    Serwuje obraz po zaszyfrowanej ścieżce, tylko z widoku galerii.
    """
    try:
        referer = request.META.get('HTTP_REFERER', '')
        sec_fetch_dest = request.META.get('HTTP_SEC_FETCH_DEST', '')
        
        if not referer or '/gallery/' not in referer:
            pass 
            
        if not request.session.get('gallery_access'):
            return HttpResponseForbidden("Dostęp zabroniony. Brak sesji.")
            
        path = decrypt_path(token)
        full_path = os.path.join(settings.MEDIA_ROOT, path)
        if not os.path.isfile(full_path):
            raise FileNotFoundError
        return FileResponse(open(full_path, 'rb'), content_type='image/jpeg')
    except Exception:
        raise Http404("Błędny token lub plik nie istnieje")


# ===============================
#         API KOSZYKA
# ===============================

@require_POST
def api_cart_add(request, photo_id: int):
    try:
        p = Photo.objects.get(pk=photo_id)
    except Photo.DoesNotExist:
        raise Http404("Photo not found")

    cart_add(request, photo_id=p.id, price=p.price, qty=1)
    return JsonResponse({"ok": True, "count": cart_count(request)})


@require_POST
def api_cart_remove(request, photo_id: int):
    try:
        p = Photo.objects.get(pk=photo_id)
    except Photo.DoesNotExist:
        raise Http404("Photo not found")

    cart_remove(request, photo_id=p.id, qty=1)
    return JsonResponse({"ok": True, "count": cart_count(request)})


@require_POST
def api_cart_delete(request, photo_id: int):
    cart = get_cart(request)
    cart.pop(str(photo_id), None)
    request.session.modified = True
    return JsonResponse({"ok": True, "count": cart_count(request)})


def api_cart_summary(request):
    cart = get_cart(request)
    if not cart:
        return JsonResponse({"ok": True, "items": [], "total": "0.00", "count": 0})

    ids = [int(pid) for pid in cart.keys()]
    photos = Photo.objects.filter(id__in=ids)
    photos_map = {p.id: p for p in photos}

    items = []
    total = 0.0

    for pid_str, entry in cart.items():
        pid = int(pid_str)
        p = photos_map.get(pid)
        if not p:
            continue
        qty = int(entry.get("qty", 0))
        price = float(entry.get("price", 0))
        line_total = qty * price
        total += line_total

        token = encrypt_path(p.image.name)
        thumb_url = request.build_absolute_uri(
            reverse("serve_encrypted_image", args=[token])
        )

        items.append({
            "id": pid,
            "qty": qty,
            "price": f"{price:.2f}",
            "line_total": f"{line_total:.2f}",
            "thumb": thumb_url,
        })

    return JsonResponse({
        "ok": True,
        "items": items,
        "total": f"{total:.2f}",
        "count": sum(i["qty"] for i in cart.values()),
    })


def cart_view(request):
    return render(request, "cart/view.html", {"cart": get_cart(request)})


# ===============================
#      PŁATNOŚCI I ZIP
# ===============================

def create_checkout_session(request):
    """
    Tworzy sesję płatności w Stripe na podstawie zawartości koszyka.
    Przekazuje session_id do URL sukcesu, aby pobrać email klienta.
    """
    cart = get_cart(request)
    if not cart:
        return redirect('home')

    domain = request.build_absolute_uri('/')[:-1] 

    line_items = []
    
    # pobieranie id zdjęć z koszyka
    ids = [int(pid) for pid in cart.keys()]
    photos = Photo.objects.filter(id__in=ids)
    photos_map = {p.id: p for p in photos}

    for pid_str, entry in cart.items():
        pid = int(pid_str)
        photo = photos_map.get(pid)
        if not photo:
            continue
            
        unit_amount = int(float(entry.get('price', 0)) * 100)
        
        line_items.append({
            'price_data': {
                'currency': 'pln',
                'product_data': {
                    'name': f'Zdjęcie #{photo.id}',
                },
                'unit_amount': unit_amount,
            },
            'quantity': 1,
        })

    if not line_items:
        return redirect('home')

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card', 'blik'],
            line_items=line_items,
            mode='payment',
            success_url=domain + reverse('payment_success') + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=domain + reverse('home'),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return JsonResponse({'error': str(e)})


def payment_success(request):
    """
    Obsługuje powrót po udanej płatności:
    1. Pobiera email ze Stripe (jeśli dostępny).
    2. Pakuje zdjęcia do ZIP.
    3. Wysyła maila z linkiem (w osobnym bloku try/except).
    4. Czyści koszyk.
    """
    # stripe get mail
    session_id = request.GET.get('session_id')
    customer_email = None

    if session_id:
        try:
            session_details = stripe.checkout.Session.retrieve(session_id)
            if session_details.customer_details:
                customer_email = session_details.customer_details.email
        except Exception as e:
            print(f"Błąd pobierania danych ze Stripe: {e}")


    cart = get_cart(request)
    if not cart:
        return render(request, 'fotoapp/homepage.html', {'error': 'Sesja wygasła lub koszyk jest pusty.'})

    ids = [int(pid) for pid in cart.keys()]
    photos = Photo.objects.filter(id__in=ids)

    if not photos.exists():
        return redirect('home')

    zip_dir = os.path.join(settings.MEDIA_ROOT, 'zips')
    if not os.path.exists(zip_dir):
        os.makedirs(zip_dir)

    session_key = request.session.session_key or 'unknown'
    zip_filename = f"zamowienie_{session_key[:8]}.zip"
    zip_filepath = os.path.join(zip_dir, zip_filename)
    
    zip_relative_url = f"{settings.MEDIA_URL}zips/{zip_filename}"
    zip_absolute_url = request.build_absolute_uri(zip_relative_url)

    # zipowanie
    try:
        with zipfile.ZipFile(zip_filepath, 'w') as zip_file:
            for photo in photos:
                original_path = photo.image.path 
                if os.path.exists(original_path):
                    zip_file.write(original_path, arcname=os.path.basename(original_path))
    except Exception as e:
        print(f"!!! BŁĄD TWORZENIA ZIP: {e}")
        return render(request, 'fotoapp/homepage.html', {'error': 'Wystąpił błąd podczas generowania plików (ZIP).'})

    # wysylanie maila
    email_sent = False
    if customer_email:
        try:
            print(f"Próbuję wysłać maila na: {customer_email}...")
            send_mail(
                subject='Twoje zdjęcia - Kilar Fotografia',
                message=f'Dziękujemy za zakup!\n\nTwoje zdjęcia są gotowe do pobrania pod tym linkiem:\n{zip_absolute_url}\n\nPozdrawiamy,\nZespół Kilar Fotografia',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[customer_email],
                fail_silently=False,
            )
            print("Mail wysłany pomyślnie!")
            email_sent = True
        except Exception as e:
            print(f"!!! BŁĄD WYSYŁANIA MAILA: {e}")

    request.session['cart'] = {}
    request.session.modified = True

    context = {
        'zip_url': zip_relative_url,
        'count': photos.count(),
        'email': customer_email,
        'email_error': not email_sent and customer_email is not None # Informacja dla template'u
    }
    return render(request, 'fotoapp/success.html', context)