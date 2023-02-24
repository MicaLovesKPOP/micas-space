var parent = document.getElementById('body');
var child = document.getElementById('bodytext');
child.style.right = child.clientWidth - child.offsetWidth + "px";

function resizeNavbar() {
    var element = document.getElementById("body");
    element.classList.toggle("alt");
    var element = document.getElementById("buttonbox");
    element.classList.toggle("alt");
    var element = document.getElementById("img");
    element.classList.toggle("alt");
    var element = document.getElementById("logo");
    element.classList.toggle("alt");
    var btn = document.getElementById("navbarSize");
    if (btn.innerHTML=="small mode") btn.innerHTML = "large mode";
    else btn.innerHTML = "small mode";
  }

function changeLightness()
{
    var btn = document.getElementById("lightnessMode");
    if (btn.innerHTML=="light mode") btn.innerHTML = "dark mode";
    else btn.innerHTML = "light mode";

    var elem = document.body
    var elem2 = document.getElementById("logo");
    if (elem.style.filter=="invert(100%)") {
        elem.style.filter = "invert(0%)";
        elem2.style.filter = "invert(0%)";
    } else {
        elem.style.filter = "invert(100%)";
        elem2.style.filter = "invert(100%)";
    }
}