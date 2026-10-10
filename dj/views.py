from django.shortcuts import render, redirect
from database import getInfo
import bcrypt
def index(request):
    login = ""
    password = ""
    if request.method == "POST":
        login = request.POST['login']
        password = request.POST["password"]

    tab = getInfo()
    print(tab)

    for elem in tab:

        if elem[0] == login and elem[1] == password:
            request.session['login'] = login
            request.session["password"] = password
            return render(request, 'welcomeScreen.html')

    return render(request, 'index.html')

def welcomeScreen(request):
    return render(request, 'welcomeScreen.html')