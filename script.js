// year in footer
document.getElementById("year").textContent = new Date().getFullYear();

// Smooth scroll
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener("click", (e) => {
    const id = a.getAttribute("href");
    if(!id || id === "#") return;
    const target = document.querySelector(id);
    if(target){
      e.preventDefault();
      target.scrollIntoView({behavior:"smooth"});
    }
  });
});

// Join list demo
const form = document.getElementById("joinForm");
if (form) {
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const email = document.getElementById("email").value.trim();
    if(!email) return;
    alert("You’re in. Welcome to KHOYA 🤝");
    document.getElementById("email").value = "";
  });
}
