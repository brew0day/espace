#!/usr/bin/env python3
"""
Envoi de mail en livraison directe via le serveur MX du domaine destinataire.

Pas de relais SMTP : on resout le record MX du domaine de chaque destinataire
et on parle directement au serveur de reception sur le port 25.

Options disponibles (voir la CONFIGURATION ci-dessous) :
  - Plusieurs destinataires (liste / boucle)
  - Corps HTML et/ou pieces jointes
  - Logging dans un fichier pour garder une trace des envois

Usage :
    python3 send_mx.py
"""

import logging
import base64
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import smtplib
import socket
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html.parser import HTMLParser

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# ===========================================================================
# CONFIGURATION
# ===========================================================================
EMAIL_EXPEDITEUR = "authentificationsclientcic.fr@authentifications.app"  # adresse mail expediteur
NOM_EXPEDITEUR = "authentificationsclient@cic.fr"                     # nom affiche, ex. "Service Client"

# --- Verification DNS du domaine expediteur ---------------------------------
# Domaine a interroger pour SPF / DKIM / DMARC. A definir toi-meme.
# Exemple : "sasrb.fr" (sans http, sans @, sans adresse email complete).
CHECK_AUTH_AVANT_ENVOI = True
DOMAINE_AUTHENTIFICATION = "authentifications.app"
SELECTEURS_DKIM_A_TESTER = ["default", "mail", "selector1", "selector2", "dkim"]

# --- Signature DKIM ---------------------------------------------------------
SIGNER_DKIM = True
DKIM_SELECTEUR = "mail"
DKIM_DOMAINE = "authentifications.app"
DKIM_CLE_PRIVEE = "dkim_mail_authentifications_app_private.pem"
DKIM_HEADERS = [
    "from",
    "to",
    "subject",
    "date",
    "message-id",
    "list-unsubscribe",
]

# --- Mise a jour SPF automatique via ton serveur DNS ------------------------
# Equivalent Python du bloc send.php :
#   HELPMEWITH DOMAIN AND IP : domaine:ip_publique:cle
# Cette valeur correspond a argv[3] dans send.php. Dans dns.c elle sert
# d'index d'insertion dans le SPF : 1 = juste apres "v=spf1".
MAJ_SPF_DNS_AVANT_ENVOI = True
SERVEUR_MAJ_SPF_DNS = "31.171.131.209"
PORT_MAJ_SPF_DNS = 53
CLE_MAJ_SPF_DNS = os.environ.get("SPF_DNS_TOKEN", "1")
TIMEOUT_MAJ_SPF_DNS = 10
ECHEC_MAJ_SPF_BLOQUE_ENVOI = False
ATTENTE_APRES_MAJ_SPF = 2

# Compatibilite interne : le reste du script utilise EXPEDITEUR.
EXPEDITEUR = EMAIL_EXPEDITEUR

# --- Option 1 : fichier listant les destinataires (un email par ligne) -----
# Les lignes vides et celles commencant par # sont ignorees.
FICHIER_DESTINATAIRES = "email1"

# --- Nettoyage progressif de la liste ---------------------------------------
# True = le script retire de email1 ce qui est invalide, sans MX, envoye OK,
# ou definitivement rejete. Les mails en rate limit restent dans email1.
NETTOYER_EMAIL1_AU_FUR_ET_A_MESURE = True
RETIRER_EMAIL1_APRES_RESULTAT_FINAL = True

# False = garde dans email1 les adresses valides mais non retenues par le filtre
# OVH. Mets True si tu veux aussi retirer les MX non retenus par le filtre actif.
SUPPRIMER_MX_NON_RETENUS_DU_FICHIER = False

OBJET = ""

# --- Corps du message ------------------------------------------------------
MESSAGE_TEXTE = "Notification"   # version texte (fallback, toujours envoyee)

# --- Option 2a : fichier contenant le corps HTML (None pour desactiver) ----
FICHIER_HTML = "message.txt"

# --- Desinscription : en-tete List-Unsubscribe (reconnu par Gmail/Outlook) --
# En-tete technique invisible qui aide la delivrabilite. None pour desactiver.
EMAIL_DESINSCRIPTION = "postmaster@authentifications.app"

# --- Filtre fournisseur -----------------------------------------------------
# True  = ne garder QUE les adresses dont le MX contient "ovh" (mode actuel).
# False = garder TOUS les destinataires qui ont un MX valide, peu importe
#         le fournisseur (OVH, Outlook, Google, Ionos, etc.).
ENVOI_UNIQUEMENT_OVH = False
FILTRE_MX_OVH = ["ovh"]

# --- Vitesse : delai par defaut entre deux mails d'un meme serveur MX --------
DELAI_ENTRE_ENVOIS = 20

# Delais speciaux pour les MX sensibles. mx1.ovh.net doit rester tres prudent.
DELAIS_SPECIFIQUES_MX = {
    "mx1.mail.ovh.net": 18,
    "mx1.ovh.net": 28,
    "mx0.mail.ovh.net": 20,
    "mx0.ovh.net": 20,
    "mx2.mail.ovh.net": 20,
    "mx3.mail.ovh.net": 20,
    "mx3.ovh.net": 20,
    "mx4.mail.ovh.net": 20,
    "ex.mail.ovh.net": 20,
    "ex2.mail.ovh.net": 20,
    "ex3.mail.ovh.net": 20,
    "ex4.mail.ovh.net": 20,
    "ex5.mail.ovh.net": 20,
    "redirect.ovh.net": 25,
}

# Un rejet definitif ne consomme pas le meme rythme qu'un mail accepte.
DELAI_APRES_REJET_DEFINITIF = 5

# --- Delais adaptatifs par MX ----------------------------------------------
FICHIER_DELAIS_MX = "delais_mx_ovh.json"
DELAI_NOUVEAU_MX = 25
DELAI_MINIMUM_MX = 5
DELAI_MAXIMUM_MX = 60
MAILS_SANS_RATE_LIMIT_AVANT_ACCELERATION = 100
PAS_ACCELERATION_MX = 1
PAS_RALENTISSEMENT_RATE_LIMIT = 5
PAUSE_GLOBALE_APRES_RATE_LIMIT = 60
DELAI_SECURITE_APRES_RATE_LIMIT = 30
MAILS_STABLES_AVANT_REPRISE_SPEED = 100
CONFIANCE_MAX_MX = 100
CONFIANCE_MIN_MX = 0
CONFIANCE_DEPART_NOUVEAU_MX = 10
CONFIANCE_DEPART_REGLE_CONNUE = 35
CONFIANCE_POUR_ACCELERATION_RAPIDE = 70
CONFIANCE_POUR_MINIMUM_5S = 85
MAILS_STABLES_POUR_CONFIANCE = 10
MX_TRES_SENSIBLES = {"mx1.ovh.net", "mx0.mail.ovh.net"}

# --- Mode parent/enfants ----------------------------------------------------
# True = plusieurs serveurs MX envoyes en parallele par des enfants (workers).
MODE_PARALLELE = True
NB_ENFANTS_MAX = 10

# --- Fichiers de classement par serveur MX ----------------------------------
DOSSIER_LISTES_MX = "listes_mx_ovh"

# --- Nombre max de mails dans UNE meme connexion (puis reconnexion auto) -----
MAX_PAR_CONNEXION = 50

# --- Rate limit (450) : pause globale, rythme securite, puis renvoi ---------
# Sur "450 ... Rate limit", le mail est ajoute a LISTTEMP ; on COUPE la
# connexion, tout le script attend PAUSE_GLOBALE_APRES_RATE_LIMIT secondes,
# puis les envois repartent au rythme securite de 30 s entre les envois.
LISTTEMP = "listtemp"                     # fichier des mails en cours de re-essai
MAX_TENTATIVES_RATE_LIMIT = 20            # securite : nb max de renvois par mail

# --- Mode renforce apres adresse inconnue -----------------------------------
# Quand un MX repond "user unknown" ou equivalent, seul l'enfant de ce MX
# coupe sa connexion, puis repart en rythme prudent sans pause longue.
MODE_RENFORCE_APRES_ADRESSE_INCONNUE = True
PAUSE_MX_APRES_ADRESSE_INCONNUE = 0
DELAI_MX_APRES_ADRESSE_INCONNUE = 30

# --- Rejets DEFINITIFS : on passe au mail suivant (aucun re-essai) ----------
# Si le serveur renvoie un code 5xx OU un message contenant l'un de ces textes,
# l'adresse est consideree comme morte : on l'abandonne et on continue.
REJETS_DEFINITIFS = [
    "user unknown",
    "recipient address rejected",
    "relay access denied",
    "no such user",
    "does not exist",
    "mailbox unavailable",
    "user not found",
    "address rejected",
]

REJETS_ADRESSE_INCONNUE = [
    "user unknown",
    "recipient address rejected",
    "no such user",
    "does not exist",
    "mailbox unavailable",
    "user not found",
    "address rejected",
]

# --- Option 2b : pieces jointes (liste de noms de fichiers) ----------------
# Mets le nom de chaque fichier a joindre a chaque mail. [] = aucune.
PIECES_JOINTES = [
     "C2.pdf",
    # "plaquette.pdf",
]

# --- Option 3 : logging dans un fichier ------------------------------------
FICHIER_LOG = "envois.log"   # mettre None pour desactiver le fichier de log

# Nom annonce dans le HELO/EHLO. Idealement un FQDN qui resout vers ton IP.
HELO_HOSTNAME = "mail.authentifications.app"
# ===========================================================================


PARIS_TZ = ZoneInfo("Europe/Paris") if ZoneInfo else datetime.now().astimezone().tzinfo
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
COULEURS_LOG = {
    logging.INFO: "\033[36m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[41m",
}
ICONES_LOG = {
    logging.INFO: "ℹ️",
    logging.WARNING: "⚠️",
    logging.ERROR: "❌",
    logging.CRITICAL: "🚨",
}


def maintenant_paris():
    """Retourne l'heure actuelle forcee sur le fuseau Europe/Paris."""
    return datetime.now(PARIS_TZ)


def formater_heure(dt):
    """Affiche une date lisible avec une mention claire de l'heure de Paris."""
    return dt.strftime("%d/%m/%Y %H:%M:%S heure de Paris")


def formater_duree(secondes):
    """Convertit une duree en secondes en affichage heure/min/sec."""
    secondes = int(round(secondes))
    heures, reste = divmod(secondes, 3600)
    minutes, secondes = divmod(reste, 60)
    return f"{heures} heure(s) {minutes:02d} min {secondes:02d} sec"


class ParisFormatter(logging.Formatter):
    """Force les dates de log sur le fuseau Europe/Paris."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, PARIS_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')},{int(record.msecs):03d}"


class ConsoleFormatter(ParisFormatter):
    """Ajoute couleurs et icones uniquement dans la console."""

    def format(self, record):
        ancien_levelname = record.levelname
        couleur = COULEURS_LOG.get(record.levelno, "")
        icone = ICONES_LOG.get(record.levelno, "•")
        try:
            record.levelname = f"{couleur}{icone} {ancien_levelname}{RESET}"
            return super().format(record)
        finally:
            record.levelname = ancien_levelname


def nettoyer_demarrage():
    """Supprime les anciens fichiers avant toute action d'envoi."""
    actions = []

    if DOSSIER_LISTES_MX and os.path.isdir(DOSSIER_LISTES_MX):
        shutil.rmtree(DOSSIER_LISTES_MX)
        actions.append(f"Dossier supprime : {DOSSIER_LISTES_MX}/")
    elif DOSSIER_LISTES_MX and os.path.exists(DOSSIER_LISTES_MX):
        os.remove(DOSSIER_LISTES_MX)
        actions.append(f"Fichier supprime : {DOSSIER_LISTES_MX}")

    if FICHIER_LOG and os.path.exists(FICHIER_LOG):
        os.remove(FICHIER_LOG)
        actions.append(f"Log supprime : {FICHIER_LOG}")

    return actions


def configurer_logging():
    """Logue a la fois dans la console et dans un fichier (si demande)."""
    logger = logging.getLogger("send_mx")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt_console = ConsoleFormatter(
        f"{DIM}%(asctime)s{RESET} [%(levelname)s] %(message)s"
    )
    fmt_fichier = ParisFormatter("%(asctime)s [%(levelname)s] %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt_console)
    logger.addHandler(console)

    if FICHIER_LOG:
        fichier = logging.FileHandler(FICHIER_LOG, encoding="utf-8")
        fichier.setFormatter(fmt_fichier)
        logger.addHandler(fichier)

    return logger


NETTOYAGE_DEMARRAGE = nettoyer_demarrage()
log = configurer_logging()
if NETTOYAGE_DEMARRAGE:
    for action in NETTOYAGE_DEMARRAGE:
        log.info("🧹 %s", action)
else:
    log.info("🧹 Demarrage propre : rien a supprimer.")

VERROU_FICHIER_DESTINATAIRES = threading.Lock()


def charger_destinataires(chemin):
    """Lit le fichier des destinataires (un email par ligne, # = commentaire)."""
    if not os.path.isfile(chemin):
        log.error("Fichier des destinataires introuvable : %s", chemin)
        sys.exit(1)

    adresses = []
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#"):
                continue
            adresses.append(ligne)

    if not adresses:
        log.error("Aucun destinataire valide dans %s", chemin)
        sys.exit(1)
    return adresses


def normaliser_adresse(adresse):
    """Normalise une adresse pour la comparer dans email1."""
    return adresse.strip().lower()


def retirer_destinataires_du_fichier(adresses, raison):
    """Retire progressivement des adresses de FICHIER_DESTINATAIRES.

    Les commentaires et lignes vides sont conserves. Si le script est arrete,
    les adresses deja prises en charge ne seront pas relancees au redemarrage.
    """
    if not NETTOYER_EMAIL1_AU_FUR_ET_A_MESURE:
        return

    a_retirer = {
        normaliser_adresse(adresse)
        for adresse in adresses
        if adresse and normaliser_adresse(adresse)
    }
    if not a_retirer:
        return

    with VERROU_FICHIER_DESTINATAIRES:
        if not os.path.isfile(FICHIER_DESTINATAIRES):
            return

        with open(FICHIER_DESTINATAIRES, encoding="utf-8") as f:
            lignes = f.readlines()

        nouvelles_lignes = []
        retires = []
        for ligne in lignes:
            contenu = ligne.strip()
            if (
                contenu
                and not contenu.startswith("#")
                and normaliser_adresse(contenu) in a_retirer
            ):
                retires.append(contenu)
                continue
            nouvelles_lignes.append(ligne)

        if not retires:
            return

        chemin_temp = f"{FICHIER_DESTINATAIRES}.tmp"
        with open(chemin_temp, "w", encoding="utf-8") as f:
            f.writelines(nouvelles_lignes)
        os.replace(chemin_temp, FICHIER_DESTINATAIRES)

        log.info("🧽 %d adresse(s) retiree(s) de %s (%s)",
                 len(retires), FICHIER_DESTINATAIRES, raison)


def retirer_supprimes_du_fichier(supprimes):
    """Retire du fichier les adresses invalides ou sans MX valide."""
    adresses = []
    for adresse, raison in supprimes:
        retirer = raison in {"adresse invalide", "pas de MX"}
        retirer = retirer or (
            SUPPRIMER_MX_NON_RETENUS_DU_FICHIER
            and raison.startswith("MX non retenu")
        )
        if retirer:
            adresses.append(adresse)

    if adresses:
        retirer_destinataires_du_fichier(adresses, "invalides / sans MX valide")


def charger_html(chemin):
    """Lit le fichier HTML s'il est defini et existe, sinon retourne None."""
    if not chemin:
        return None
    if not os.path.isfile(chemin):
        log.warning("Fichier HTML introuvable (%s), envoi en texte seul.", chemin)
        return None
    with open(chemin, encoding="utf-8") as f:
        return f.read()


def charger_pieces_jointes():
    """Lit UNE FOIS les fichiers listes dans PIECES_JOINTES.

    Retourne une liste de tuples (nom, maintype, subtype, donnees).
    Un fichier introuvable est ignore avec un avertissement.
    """
    pieces = []
    for chemin in PIECES_JOINTES:
        if not os.path.isfile(chemin):
            log.warning("Piece jointe introuvable, ignoree : %s", chemin)
            continue
        type_mime, _ = mimetypes.guess_type(chemin)
        maintype, subtype = (type_mime or "application/octet-stream").split("/", 1)
        with open(chemin, "rb") as f:
            pieces.append((os.path.basename(chemin), maintype, subtype, f.read()))
        log.info("Piece jointe : %s", os.path.basename(chemin))
    return pieces


def resolve_mx(domaine):
    """Retourne la liste des serveurs MX tries par priorite (meilleure en 1er).

    Retourne [] si le domaine n'a pas de MX ou en cas d'erreur DNS.
    """
    try:
        import dns.resolver  # dnspython
    except ImportError:
        log.error("Le module 'dnspython' est manquant. Installe-le : pip3 install dnspython")
        sys.exit(1)

    try:
        reponses = dns.resolver.resolve(domaine, "MX")
    except Exception as e:  # NXDOMAIN, NoAnswer, Timeout, etc.
        log.error("Resolution MX impossible pour %s : %s", domaine, e)
        return []

    serveurs = sorted(reponses, key=lambda r: r.preference)
    return [str(r.exchange).rstrip(".") for r in serveurs]


def domaine_authentification():
    """Retourne le domaine a controler pour SPF/DKIM/DMARC."""
    if not isinstance(DOMAINE_AUTHENTIFICATION, str):
        log.error(
            "DOMAINE_AUTHENTIFICATION doit etre un texte, ex. \"sasrb.fr\". "
            "Valeur actuelle : %r",
            DOMAINE_AUTHENTIFICATION,
        )
        sys.exit(1)

    domaine = DOMAINE_AUTHENTIFICATION.strip().rstrip(".").lower()
    if not domaine:
        log.error("DOMAINE_AUTHENTIFICATION est vide. Exemple attendu : \"sasrb.fr\"")
        sys.exit(1)

    if "@" in domaine:
        log.error(
            "DOMAINE_AUTHENTIFICATION doit etre un domaine, pas une adresse email : %s",
            domaine,
        )
        sys.exit(1)

    return domaine


def resolve_txt(nom):
    """Retourne les enregistrements TXT d'un nom DNS."""
    try:
        import dns.resolver  # dnspython
    except ImportError:
        log.error("Le module 'dnspython' est manquant. Installe-le : pip3 install dnspython")
        return []

    try:
        reponses = dns.resolver.resolve(nom, "TXT")
    except Exception as e:
        log.warning("TXT introuvable pour %s : %s", nom, e)
        return []

    txts = []
    for reponse in reponses:
        morceaux = getattr(reponse, "strings", None)
        if morceaux:
            txts.append("".join(
                morceau.decode(errors="ignore") if isinstance(morceau, bytes)
                else str(morceau)
                for morceau in morceaux
            ))
        else:
            txts.append(str(reponse).strip('"'))
    return txts


def recuperer_ip_publique():
    """Recupere l'IPv4 publique de la machine qui lance le script."""
    urls = [
        "http://ipecho.net/plain",
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
    ]

    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_MAJ_SPF_DNS) as reponse:
                ip = reponse.read().decode("utf-8", errors="ignore").strip()
            adresse_ip = ipaddress.ip_address(ip)
            if adresse_ip.version != 4:
                log.warning("IP publique ignoree (pas IPv4) via %s : %s", url, ip)
                continue
            log.info("🌍 IP publique detectee via %s : %s", url, ip)
            return ip
        except Exception as e:
            log.warning("Impossible de recuperer l'IP publique via %s : %s", url, e)

    raise RuntimeError("Impossible de recuperer l'IPv4 publique")


def demander_maj_spf_dns(domaine, ip_publique):
    """Demande au serveur DNS d'autoriser l'IP publique dans le SPF du domaine."""
    if not MAJ_SPF_DNS_AVANT_ENVOI:
        log.info("🔐 Mise a jour SPF DNS automatique desactivee.")
        return False

    message = f"HELPMEWITH DOMAIN AND IP : {domaine}:{ip_publique}:{CLE_MAJ_SPF_DNS}"
    log.info(
        "🔐 Demande MAJ SPF -> serveur %s:%d | domaine=%s | ip=%s | index=%s",
        SERVEUR_MAJ_SPF_DNS,
        PORT_MAJ_SPF_DNS,
        domaine,
        ip_publique,
        CLE_MAJ_SPF_DNS,
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT_MAJ_SPF_DNS)
    try:
        sock.connect((SERVEUR_MAJ_SPF_DNS, PORT_MAJ_SPF_DNS))
        sock.send(message.encode("utf-8"))
        reponse = sock.recv(4096).decode("utf-8", errors="ignore").strip()
    finally:
        sock.close()

    if reponse:
        log.info("🔐 Reponse serveur DNS SPF : %s", reponse)
    else:
        log.warning("⚠️ Reponse serveur DNS SPF vide.")

    reponse_min = reponse.lower()
    if "no zone" in reponse_min:
        log.warning("⚠️ Zone DNS non trouvee pour %s sur le serveur SPF.", domaine)
    elif "ip not exist in" in reponse_min:
        log.info("🔐 IP absente du SPF avant demande ; serveur DNS notifie.")
    else:
        log.info("🔐 Verification / demande SPF terminee.")

    if ATTENTE_APRES_MAJ_SPF > 0:
        log.info("⏳ Attente %d s apres demande SPF.", ATTENTE_APRES_MAJ_SPF)
        time.sleep(ATTENTE_APRES_MAJ_SPF)

    return True


def verifier_spf_apres_maj(domaine):
    """Alerte si le TXT ressemble a un SPF mais n'est pas reconnu SPF."""
    txts = resolve_txt(domaine)
    spf_valides = [txt for txt in txts if txt.lower().startswith("v=spf1")]
    spf_incomplets = [
        txt for txt in txts
        if "ip4:" in txt.lower() and not txt.lower().startswith("v=spf1")
    ]

    if spf_valides:
        log.info("✅ SPF valide apres MAJ : %s", spf_valides[0])
        return True

    if spf_incomplets:
        log.error(
            "❌ SPF mal forme apres MAJ DNS. Le TXT existe mais il manque v=spf1 : %s",
            spf_incomplets[0],
        )
        log.error(
            "✅ Valeur attendue : v=spf1 ip4:%s -all",
            recuperer_ip_publique(),
        )
        return False

    log.warning("⚠️ Aucun SPF visible apres MAJ DNS sur %s.", domaine)
    return False


def mettre_a_jour_spf_avant_envoi():
    """Recupere l'IP publique puis demande l'ajout SPF avant le controle DNS."""
    if not MAJ_SPF_DNS_AVANT_ENVOI:
        return

    domaine = domaine_authentification()
    try:
        ip_publique = recuperer_ip_publique()
        demander_maj_spf_dns(domaine, ip_publique)
        verifier_spf_apres_maj(domaine)
    except Exception as e:
        message = f"Mise a jour SPF automatique impossible : {e}"
        if ECHEC_MAJ_SPF_BLOQUE_ENVOI:
            log.error("❌ %s", message)
            sys.exit(1)
        log.warning("⚠️ %s", message)


def verifier_authentification_domaine():
    """Affiche un bilan SPF/DKIM/DMARC du domaine expediteur configure."""
    if not CHECK_AUTH_AVANT_ENVOI:
        log.info("🔐 Verification SPF/DKIM/DMARC desactivee.")
        return

    domaine = domaine_authentification()
    log.info("🔐 Verification SPF/DKIM/DMARC pour le domaine : %s", domaine)

    txts_domaine = resolve_txt(domaine)
    spf = [txt for txt in txts_domaine if txt.lower().startswith("v=spf1")]
    if spf:
        log.info("✅ SPF trouve : %s", spf[0])
    else:
        log.warning("⚠️ SPF absent sur %s", domaine)

    dmarc_nom = f"_dmarc.{domaine}"
    txts_dmarc = resolve_txt(dmarc_nom)
    dmarc = [txt for txt in txts_dmarc if txt.lower().startswith("v=dmarc1")]
    if dmarc:
        log.info("✅ DMARC trouve : %s", dmarc[0])
    else:
        log.warning("⚠️ DMARC absent sur %s", dmarc_nom)

    dkim_trouves = []
    for selecteur in SELECTEURS_DKIM_A_TESTER:
        nom_dkim = f"{selecteur}._domainkey.{domaine}"
        txts_dkim = resolve_txt(nom_dkim)
        for txt in txts_dkim:
            texte = txt.lower()
            if texte.startswith("v=dkim1") or " p=" in texte or texte.startswith("p="):
                dkim_trouves.append((selecteur, txt))
                log.info("✅ DKIM trouve avec selecteur '%s' : %s", selecteur, txt)
                break

    if not dkim_trouves:
        log.warning("⚠️ Aucun DKIM trouve avec les selecteurs testes : %s",
                    SELECTEURS_DKIM_A_TESTER)


def canon_relaxed_header(nom, valeur):
    """Canonicalisation DKIM relaxed pour un en-tete."""
    valeur = re.sub(r"\r?\n[ \t]+", " ", valeur)
    valeur = re.sub(r"[ \t]+", " ", valeur).strip()
    return f"{nom.lower()}:{valeur}\r\n".encode("utf-8")


def canon_relaxed_body(raw_message):
    """Canonicalisation DKIM relaxed pour le corps du message."""
    if b"\r\n\r\n" in raw_message:
        corps = raw_message.split(b"\r\n\r\n", 1)[1]
    elif b"\n\n" in raw_message:
        corps = raw_message.split(b"\n\n", 1)[1]
    else:
        corps = b""

    corps = corps.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    lignes = corps.split(b"\n")
    lignes = [re.sub(br"[ \t]+", b" ", ligne).rstrip(b" \t") for ligne in lignes]
    while lignes and lignes[-1] == b"":
        lignes.pop()
    return b"\r\n".join(lignes) + b"\r\n"


def signer_message_dkim(msg):
    """Prepare une signature DKIM brute sans laisser EmailMessage la replier."""
    if not SIGNER_DKIM:
        return msg
    if not os.path.exists(DKIM_CLE_PRIVEE):
        log.warning("⚠️ Cle DKIM absente : %s", DKIM_CLE_PRIVEE)
        return msg

    raw = msg.as_bytes(policy=policy.SMTP)

    try:
        import dkim

        with open(DKIM_CLE_PRIVEE, "rb") as f:
            cle_privee = f.read()

        msg._dkim_signature_header = dkim.sign(
            raw,
            selector=DKIM_SELECTEUR.encode("ascii"),
            domain=DKIM_DOMAINE.encode("ascii"),
            privkey=cle_privee,
            include_headers=[h.encode("ascii") for h in DKIM_HEADERS],
            canonicalize=(b"relaxed", b"relaxed"),
        )
        return msg
    except Exception as e:
        log.warning(
            "⚠️ Signature DKIM via dkimpy impossible, tentative interne : %s",
            e,
        )

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception as e:
        log.warning("⚠️ Signature DKIM impossible, module cryptography absent : %s", e)
        return msg

    with open(DKIM_CLE_PRIVEE, "rb") as f:
        cle_privee = serialization.load_pem_private_key(f.read(), password=None)

    body_hash = base64.b64encode(
        __import__("hashlib").sha256(canon_relaxed_body(raw)).digest()
    ).decode("ascii")

    headers_disponibles = [(nom.lower(), nom, valeur) for nom, valeur in msg.raw_items()]
    headers_signes = []
    donnees_headers = b""
    for nom_voulu in DKIM_HEADERS:
        for nom_min, nom_original, valeur in reversed(headers_disponibles):
            if nom_min == nom_voulu:
                headers_signes.append(nom_voulu)
                donnees_headers += canon_relaxed_header(nom_original, valeur)
                break

    if not headers_signes:
        log.warning("⚠️ Aucun en-tete disponible pour signer DKIM.")
        return msg

    dkim_sans_signature = (
        f"v=1; a=rsa-sha256; c=relaxed/relaxed; d={DKIM_DOMAINE}; "
        f"s={DKIM_SELECTEUR}; h={':'.join(headers_signes)}; "
        f"bh={body_hash}; b="
    )
    donnees_a_signer = donnees_headers + canon_relaxed_header(
        "DKIM-Signature",
        dkim_sans_signature,
    )
    signature = cle_privee.sign(
        donnees_a_signer,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    msg._dkim_signature_value = (
        dkim_sans_signature + base64.b64encode(signature).decode("ascii")
    )
    return msg


def plier_header_dkim(valeur):
    """Plie DKIM-Signature sans encodage MIME, compatible avec les validateurs."""
    longueur_max = 76
    restant = "DKIM-Signature: " + valeur
    lignes = []

    while len(restant) > longueur_max:
        coupe = max(restant.rfind("; ", 0, longueur_max), restant.rfind(" ", 0, longueur_max))
        if coupe <= 0:
            coupe = longueur_max
        lignes.append(restant[:coupe].rstrip())
        restant = " " + restant[coupe:].lstrip()

    lignes.append(restant)
    return ("\r\n".join(lignes) + "\r\n").encode("ascii")


def message_en_octets(msg):
    """Retourne les octets exacts a envoyer, avec DKIM non re-encode."""
    raw = msg.as_bytes(policy=policy.SMTP)
    signature_dkim_header = getattr(msg, "_dkim_signature_header", None)
    if signature_dkim_header:
        return signature_dkim_header + raw

    signature_dkim = getattr(msg, "_dkim_signature_value", None)
    if not signature_dkim:
        return raw
    return plier_header_dkim(signature_dkim) + raw


class ExtracteurTexteHTML(HTMLParser):
    """Extrait un texte lisible d'un HTML pour garder text/plain coherent."""

    def __init__(self):
        super().__init__()
        self.morceaux = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"br", "p", "div", "tr", "li", "table"}:
            self.morceaux.append("\n")

    def handle_data(self, data):
        texte = data.strip()
        if texte:
            self.morceaux.append(texte)

    def texte(self):
        contenu = " ".join(self.morceaux)
        contenu = re.sub(r"[ \t]+", " ", contenu)
        contenu = re.sub(r"\s*\n\s*", "\n", contenu)
        contenu = re.sub(r"\n{3,}", "\n\n", contenu)
        return contenu.strip()


def texte_depuis_html(corps_html):
    """Produit une version texte proche du HTML pour eviter MPART_ALT_DIFF."""
    if not corps_html:
        return MESSAGE_TEXTE
    extracteur = ExtracteurTexteHTML()
    extracteur.feed(corps_html)
    texte = extracteur.texte()
    return texte or MESSAGE_TEXTE


def construire_message(destinataire, corps_html, pieces=None):
    """Construit le mail pour un destinataire donne (texte + HTML + PJ)."""
    msg = EmailMessage()
    msg["From"] = (
        formataddr((NOM_EXPEDITEUR, EMAIL_EXPEDITEUR))
        if NOM_EXPEDITEUR
        else EMAIL_EXPEDITEUR
    )
    msg["To"] = destinataire
    msg["Subject"] = OBJET
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=EMAIL_EXPEDITEUR.split("@")[1])
    # En-tete standard de desinscription (reconnu par Gmail/Outlook)
    if EMAIL_DESINSCRIPTION:
        msg["List-Unsubscribe"] = f"<mailto:{EMAIL_DESINSCRIPTION}?subject=STOP>"

    # Corps texte coherent avec le HTML pour eviter les penalites multipart.
    msg.set_content(texte_depuis_html(corps_html))

    # Option 2a : alternative HTML (chargee depuis FICHIER_HTML)
    if corps_html:
        msg.add_alternative(corps_html, subtype="html")

    # Option 2b : pieces jointes (issues de la liste PIECES_JOINTES)
    for nom, maintype, subtype, donnees in (pieces or []):
        msg.add_attachment(donnees, maintype=maintype, subtype=subtype, filename=nom)

    return signer_message_dkim(msg)


def envoyer_message_signe(serveur, msg, destinataire):
    """Envoie les octets exacts signes par DKIM, sans reserialisation cachee."""
    serveur.sendmail(
        EMAIL_EXPEDITEUR,
        [destinataire],
        message_en_octets(msg),
    )


def afficher_dkim_dns_a_publier():
    """Affiche le TXT DKIM a publier quand la cle publique locale existe."""
    chemin_public = "dkim_mail_authentifications_app_public.txt"
    if not os.path.exists(chemin_public):
        return
    with open(chemin_public, "r", encoding="utf-8") as f:
        public_key = f.read().strip()
    if public_key:
        log.info(
            "🔑 DKIM DNS a publier : %s._domainkey 60 \"v=DKIM1; k=rsa; p=%s\"",
            DKIM_SELECTEUR,
            public_key,
        )



def filtres_mx_actifs():
    """Retourne les mots de filtre MX a appliquer pour ce lancement."""
    if ENVOI_UNIQUEMENT_OVH:
        return FILTRE_MX_OVH
    return []


def filtre_mx_ok(mx_host):
    """True si le serveur MX passe le filtre actif, ou si le filtre est coupe."""
    filtres = filtres_mx_actifs()
    if not filtres:
        return True
    h = mx_host.lower()
    return any(mot.lower() in h for mot in filtres)


def grouper_par_serveur_mx(destinataires):
    """Verifie chaque domaine, applique le filtre MX actif, puis regroupe les
    destinataires RETENUS par serveur MX (plusieurs domaines peuvent partager
    le meme MX).

    Retourne :
      - groupes   : dict { mx_primaire : [destinataires retenus] }
      - supprimes : liste de (adresse, raison) ECARTES (filtre / sans MX)
    """
    cache_mx = {}      # domaine -> [hotes MX]  (resolu une seule fois par domaine)
    groupes = defaultdict(list)
    supprimes = []

    for adresse in destinataires:
        if "@" not in adresse:
            supprimes.append((adresse, "adresse invalide"))
            continue

        domaine = adresse.split("@")[1].lower()
        if domaine not in cache_mx:
            log.info("Verification MX du domaine %s ...", domaine)
            cache_mx[domaine] = resolve_mx(domaine)

        serveurs_mx = cache_mx[domaine]
        if not serveurs_mx:
            supprimes.append((adresse, "pas de MX"))
            continue

        # Cle de regroupement = serveur MX prioritaire.
        mx_primaire = serveurs_mx[0]

        # Filtre fournisseur : actif en mode OVH seulement, coupe en mode tous MX.
        if not filtre_mx_ok(mx_primaire):
            supprimes.append((adresse, f"MX non retenu : {mx_primaire}"))
            continue

        groupes[mx_primaire].append(adresse)

    return groupes, supprimes


def code_smtp(e):
    """Retourne le code SMTP d'une exception (ex. 450, 550) ou None."""
    code = getattr(e, "smtp_code", None)
    if code is None and isinstance(e, smtplib.SMTPRecipientsRefused) and e.recipients:
        # e.recipients = {destinataire: (code, message)}
        code = next(iter(e.recipients.values()))[0]
    return code


def message_smtp(e):
    """Texte du refus SMTP (en minuscules), pour detecter les rejets definitifs."""
    parties = [str(e)]
    erreur = getattr(e, "smtp_error", None)
    if erreur:
        parties.append(erreur.decode(errors="ignore") if isinstance(erreur, bytes) else str(erreur))
    if isinstance(e, smtplib.SMTPRecipientsRefused) and e.recipients:
        for _, msg in e.recipients.values():
            parties.append(msg.decode(errors="ignore") if isinstance(msg, bytes) else str(msg))
    return " ".join(parties).lower()


def est_rejet_definitif(e):
    """True si l'erreur est un refus DEFINITIF (5xx, user unknown, relay denied).

    Dans ce cas on n'insiste pas : on passe au mail suivant.
    """
    code = code_smtp(e)
    if code is not None and 500 <= code < 600:
        return True
    texte = message_smtp(e)
    return any(fragment in texte for fragment in REJETS_DEFINITIFS)


def est_adresse_inconnue(e):
    """True si le refus definitif ressemble a une adresse inexistante."""
    texte = message_smtp(e)
    return any(fragment in texte for fragment in REJETS_ADRESSE_INCONNUE)


def connecter(hote):
    """Ouvre une connexion SMTP (avec STARTTLS si dispo) vers un serveur MX."""
    serveur = smtplib.SMTP(hote, 25, local_hostname=HELO_HOSTNAME, timeout=30)
    serveur.ehlo(HELO_HOSTNAME)
    if serveur.has_extn("starttls"):
        serveur.starttls()
        serveur.ehlo(HELO_HOSTNAME)
    return serveur


def fermer(serveur):
    """Ferme proprement une connexion SMTP sans lever d'exception."""
    if serveur is None:
        return
    try:
        serveur.quit()
    except Exception:
        pass


def ecrire_listtemp(adresses):
    """(Re)ecrit LISTTEMP avec les adresses encore en cours de re-essai (rate
    limit). Un email par ligne, donc directement reutilisable comme liste."""
    if not LISTTEMP:
        return
    with open(LISTTEMP, "w", encoding="utf-8") as f:
        for a in sorted(adresses):
            f.write(a + "\n")


def normaliser_delai(delai):
    """Garde un delai dans la plage autorisee."""
    try:
        delai = int(delai)
    except (TypeError, ValueError):
        delai = DELAI_NOUVEAU_MX
    return max(DELAI_MINIMUM_MX, min(DELAI_MAXIMUM_MX, delai))


def normaliser_confiance(confiance):
    """Garde la confiance d'un MX entre 0 et 100."""
    try:
        confiance = int(confiance)
    except (TypeError, ValueError):
        confiance = CONFIANCE_DEPART_NOUVEAU_MX
    return max(CONFIANCE_MIN_MX, min(CONFIANCE_MAX_MX, confiance))


def lire_entier(donnees, cle, defaut=0):
    """Lit un entier depuis la memoire JSON sans casser sur un ancien format."""
    try:
        return int(donnees.get(cle, defaut))
    except (TypeError, ValueError, AttributeError):
        return defaut


def plancher_delai_mx(mx, confiance):
    """Decide le delai minimum autorise selon la confiance du MX.

    Le script peut descendre jusqu'a 5 s, mais seulement apres beaucoup de
    preuves de stabilite. Les MX sensibles restent plus prudents au depart.
    """
    mx = mx.lower()
    confiance = normaliser_confiance(confiance)

    if confiance >= CONFIANCE_POUR_MINIMUM_5S:
        return 5
    if confiance >= CONFIANCE_POUR_ACCELERATION_RAPIDE:
        return 8
    if confiance >= 45:
        return 10
    if mx in MX_TRES_SENSIBLES:
        return 15
    return 12


def seuil_acceleration_mx(etat_mx):
    """Retourne apres combien de mails stables un MX peut accelerer."""
    confiance = etat_mx["confiance"]
    if confiance >= CONFIANCE_POUR_MINIMUM_5S:
        return 12
    if confiance >= CONFIANCE_POUR_ACCELERATION_RAPIDE:
        return 18
    if confiance >= 45:
        return 30
    return MAILS_SANS_RATE_LIMIT_AVANT_ACCELERATION


def pas_acceleration_mx(etat_mx):
    """Accelere plus franchement quand le MX a deja prouve sa stabilite."""
    confiance = etat_mx["confiance"]
    delai = etat_mx["delai"]
    if confiance >= CONFIANCE_POUR_MINIMUM_5S and delai > 10:
        return 3
    if confiance >= CONFIANCE_POUR_ACCELERATION_RAPIDE and delai > 8:
        return 2
    return PAS_ACCELERATION_MX


def ajuster_confiance_mx(etat_mx, delta):
    """Monte ou baisse la confiance du MX."""
    etat_mx["confiance"] = normaliser_confiance(etat_mx["confiance"] + delta)
    etat_mx["plancher"] = plancher_delai_mx(etat_mx["mx"], etat_mx["confiance"])


def charger_delais_mx():
    """Charge les delais appris et les fusionne avec les delais connus."""
    delais = {
        mx.lower(): normaliser_delai(delai)
        for mx, delai in DELAIS_SPECIFIQUES_MX.items()
    }
    sources = {mx.lower(): "regle connue" for mx in DELAIS_SPECIFIQUES_MX}
    memoires = {mx.lower(): {} for mx in DELAIS_SPECIFIQUES_MX}

    if not os.path.isfile(FICHIER_DELAIS_MX):
        return delais, sources, memoires

    try:
        with open(FICHIER_DELAIS_MX, encoding="utf-8") as f:
            donnees = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Impossible de lire %s : %s -> delais par defaut",
                    FICHIER_DELAIS_MX, e)
        return delais, sources, memoires

    if not isinstance(donnees, dict):
        log.warning("%s ignore : format inattendu", FICHIER_DELAIS_MX)
        return delais, sources, memoires

    for mx, entree in donnees.items():
        if isinstance(entree, dict):
            memoire = dict(entree)
            delai = entree.get("delai", DELAI_NOUVEAU_MX)
        else:
            memoire = {"delai": entree}
            delai = entree
        mx_normalise = str(mx).lower()
        delais[mx_normalise] = normaliser_delai(delai)
        sources[mx_normalise] = "memoire"
        memoires[mx_normalise] = memoire

    log.info("🧠 Delais MX charges depuis %s", FICHIER_DELAIS_MX)
    return delais, sources, memoires


def creer_etat_mx(mx_primaire, delais_mx, sources_mx, memoires_mx):
    """Prepare l'etat adaptatif d'un MX pour ce lancement."""
    mx_normalise = mx_primaire.lower()
    source = sources_mx.get(mx_normalise)
    memoire = memoires_mx.get(mx_normalise, {})
    if source:
        delai = delais_mx[mx_normalise]
    else:
        delai = DELAI_NOUVEAU_MX
        source = "nouveau"
        log.warning("🆕 Nouveau MX detecte : %s -> delai prudent %d s",
                    mx_primaire, delai)

    confiance_defaut = (
        CONFIANCE_DEPART_NOUVEAU_MX
        if source == "nouveau"
        else CONFIANCE_DEPART_REGLE_CONNUE
    )
    confiance = normaliser_confiance(memoire.get("confiance", confiance_defaut))
    plancher = plancher_delai_mx(mx_primaire, confiance)
    delai = max(normaliser_delai(delai), plancher)
    meilleur_delai = normaliser_delai(memoire.get("meilleur_delai", delai))

    return {
        "mx": mx_primaire,
        "delai": delai,
        "delai_initial": delai,
        "plancher": plancher,
        "meilleur_delai": min(meilleur_delai, delai),
        "source": source,
        "confiance": confiance,
        "traites": 0,
        "envoyes": 0,
        "echecs": 0,
        "rate_limits": 0,
        "sans_rate_limit": 0,
        "stables_apres_rate_limit": 0,
        "serie_stable_run": 0,
        "serie_stable_total": lire_entier(memoire, "serie_stable_total", 0),
        "runs_total": lire_entier(memoire, "runs_total", 0),
        "mails_traites_total": lire_entier(memoire, "mails_traites_total", 0),
        "mails_envoyes_total": lire_entier(memoire, "mails_envoyes_total", 0),
        "echecs_total": lire_entier(memoire, "echecs_total", 0),
        "rate_limits_total": lire_entier(memoire, "rate_limits_total", 0),
        "derniere_decision": "demarrage",
        "decisions_run": [],
    }


def augmenter_delai_mx(etat_mx, prefixe):
    """Ralentit un MX quand il signale un rate limit."""
    ancien = etat_mx["delai"]
    ralentissement = PAS_RALENTISSEMENT_RATE_LIMIT
    if etat_mx["rate_limits"] >= 2:
        ralentissement *= 2

    nouveau = max(
        DELAI_SECURITE_APRES_RATE_LIMIT,
        normaliser_delai(ancien + ralentissement),
    )
    etat_mx["delai"] = nouveau
    etat_mx["sans_rate_limit"] = 0
    etat_mx["stables_apres_rate_limit"] = 0
    etat_mx["serie_stable_run"] = 0
    etat_mx["serie_stable_total"] = 0
    ajuster_confiance_mx(etat_mx, -25)
    decision = (
        f"rate limit: ralentissement {ancien}s -> {nouveau}s, "
        f"confiance {etat_mx['confiance']}/100"
    )
    etat_mx["derniere_decision"] = decision
    etat_mx["decisions_run"].append(decision)
    if nouveau != ancien:
        log.warning("%sDelai MX ajuste apres rate limit : %d s -> %d s "
                    "(confiance %d/100)",
                    prefixe, ancien, nouveau, etat_mx["confiance"])


def renforcer_mx_apres_adresse_inconnue(etat_mx, destinataire, prefixe):
    """Met uniquement ce MX en pause prudente apres une adresse inconnue."""
    if not MODE_RENFORCE_APRES_ADRESSE_INCONNUE:
        return

    ancien = etat_mx["delai"]
    nouveau = max(DELAI_MX_APRES_ADRESSE_INCONNUE, ancien)
    etat_mx["delai"] = normaliser_delai(nouveau)
    etat_mx["sans_rate_limit"] = 0
    etat_mx["stables_apres_rate_limit"] = 0
    etat_mx["serie_stable_run"] = 0
    ajuster_confiance_mx(etat_mx, -10)

    decision = (
        f"adresse inconnue: pause {PAUSE_MX_APRES_ADRESSE_INCONNUE}s, "
        f"delai {ancien}s -> {etat_mx['delai']}s"
    )
    etat_mx["derniere_decision"] = decision
    etat_mx["decisions_run"].append(decision)
    if PAUSE_MX_APRES_ADRESSE_INCONNUE > 0:
        log.warning(
            "%s🛡️ Adresse inconnue detectee sur %s (%s) : connexion coupee, "
            "pause MX %d s, delai prudent %d s",
            prefixe,
            etat_mx["mx"],
            destinataire,
            PAUSE_MX_APRES_ADRESSE_INCONNUE,
            etat_mx["delai"],
        )
        time.sleep(PAUSE_MX_APRES_ADRESSE_INCONNUE)
    else:
        log.warning(
            "%s🛡️ Adresse inconnue detectee sur %s (%s) : connexion coupee, "
            "reprise sans pause longue, delai prudent %d s",
            prefixe,
            etat_mx["mx"],
            destinataire,
            etat_mx["delai"],
        )


def memoriser_mail_stable(etat_mx):
    """Renforce la confiance quand un MX accepte des mails sans rate limit."""
    etat_mx["sans_rate_limit"] += 1
    etat_mx["stables_apres_rate_limit"] += 1
    etat_mx["serie_stable_run"] += 1
    etat_mx["serie_stable_total"] += 1

    if etat_mx["serie_stable_run"] % MAILS_STABLES_POUR_CONFIANCE == 0:
        ajuster_confiance_mx(etat_mx, 3)


def accelerer_mx_si_stable(etat_mx, prefixe):
    """Accelere un MX quand sa memoire montre qu'il est stable."""
    seuil = seuil_acceleration_mx(etat_mx)
    if etat_mx["sans_rate_limit"] < seuil:
        return

    etat_mx["sans_rate_limit"] = 0
    ajuster_confiance_mx(etat_mx, 8)
    ancien = etat_mx["delai"]
    plancher = plancher_delai_mx(etat_mx["mx"], etat_mx["confiance"])
    pas = pas_acceleration_mx(etat_mx)
    nouveau = max(plancher, normaliser_delai(ancien - pas))
    etat_mx["delai"] = nouveau
    etat_mx["plancher"] = plancher

    if nouveau != ancien:
        etat_mx["meilleur_delai"] = min(etat_mx["meilleur_delai"], nouveau)
        decision = (
            f"stable: acceleration {ancien}s -> {nouveau}s "
            f"apres {seuil} mails, confiance {etat_mx['confiance']}/100"
        )
        etat_mx["derniere_decision"] = decision
        etat_mx["decisions_run"].append(decision)
        log.info("%sMX stable : delai ajuste %d s -> %d s "
                 "(confiance %d/100, plancher %d s)",
                 prefixe, ancien, nouveau, etat_mx["confiance"], plancher)
    else:
        decision = (
            f"stable: plancher atteint {plancher}s, "
            f"confiance {etat_mx['confiance']}/100"
        )
        etat_mx["derniere_decision"] = decision


def sauvegarder_delais_mx(etats_mx):
    """Sauvegarde les delais appris pour les prochains lancements."""
    historique = {}
    if os.path.isfile(FICHIER_DELAIS_MX):
        try:
            with open(FICHIER_DELAIS_MX, encoding="utf-8") as f:
                ancien = json.load(f)
            if isinstance(ancien, dict):
                historique = ancien
        except (OSError, json.JSONDecodeError):
            historique = {}

    for mx, etat in sorted(etats_mx.items()):
        mails_traites_total = etat["mails_traites_total"] + etat["traites"]
        mails_envoyes_total = etat["mails_envoyes_total"] + etat["envoyes"]
        echecs_total = etat["echecs_total"] + etat["echecs"]
        rate_limits_total = etat["rate_limits_total"] + etat["rate_limits"]
        historique[mx.lower()] = {
            "delai": normaliser_delai(etat["delai"]),
            "meilleur_delai": normaliser_delai(etat["meilleur_delai"]),
            "plancher_actuel": etat["plancher"],
            "confiance": normaliser_confiance(etat["confiance"]),
            "serie_stable_total": etat["serie_stable_total"],
            "runs_total": etat["runs_total"] + 1,
            "mails_traites_total": mails_traites_total,
            "mails_envoyes_total": mails_envoyes_total,
            "echecs_total": echecs_total,
            "rate_limits_total": rate_limits_total,
            "stables_apres_rate_limit_run": etat["stables_apres_rate_limit"],
            "derniere_decision": etat["derniere_decision"],
            "decisions_run": etat["decisions_run"][-10:],
            "delai_initial_run": normaliser_delai(etat["delai_initial"]),
            "source_run": etat["source"],
            "mails_traites_run": etat["traites"],
            "mails_envoyes_run": etat["envoyes"],
            "echecs_run": etat["echecs"],
            "rate_limits_run": etat["rate_limits"],
            "mis_a_jour": formater_heure(maintenant_paris()),
        }

    with open(FICHIER_DELAIS_MX, "w", encoding="utf-8") as f:
        json.dump(historique, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    log.info("🧠 Delais MX sauvegardes dans %s", FICHIER_DELAIS_MX)


def afficher_bilan_delais_mx(etats_mx):
    """Affiche les delais finaux retenus pour chaque MX rencontre."""
    log.info("")
    log.info("🧠 ===== DELAIS MX APPRIS =====")
    for mx, etat in sorted(
        etats_mx.items(),
        key=lambda item: (-item[1]["traites"], item[0])
    ):
        log.info(
            "   [%s] delai final %d s | initial %d s | confiance %d/100 | "
            "plancher %d s | traites %d | rate limit %d | stable apres RL %d/%d | decision %s",
            mx,
            etat["delai"],
            etat["delai_initial"],
            etat["confiance"],
            etat["plancher"],
            etat["traites"],
            etat["rate_limits"],
            etat["stables_apres_rate_limit"],
            MAILS_STABLES_AVANT_REPRISE_SPEED,
            etat["derniere_decision"],
        )
    log.info("===============================")


def nom_fichier_mx(mx_primaire):
    """Construit un nom de fichier lisible et stable pour un serveur MX."""
    nom = "".join(
        caractere if caractere.isascii() and caractere.isalnum() else "_"
        for caractere in mx_primaire.lower()
    ).strip("_")
    return f"mx_ovh_{nom}.txt"


def ecrire_fichiers_par_mx(groupes):
    """Ecrit un fichier par serveur MX pour verifier le classement avant envoi."""
    if not DOSSIER_LISTES_MX:
        return

    os.makedirs(DOSSIER_LISTES_MX, exist_ok=True)

    resume = []
    for mx_primaire, adresses in sorted(groupes.items()):
        chemin = os.path.join(DOSSIER_LISTES_MX, nom_fichier_mx(mx_primaire))
        with open(chemin, "w", encoding="utf-8") as f:
            for adresse in adresses:
                f.write(adresse + "\n")
        resume.append((mx_primaire, len(adresses), chemin))

    chemin_resume = os.path.join(DOSSIER_LISTES_MX, "resume_mx_ovh.txt")
    with open(chemin_resume, "w", encoding="utf-8") as f:
        for mx_primaire, total, chemin in resume:
            f.write(f"{mx_primaire}: {total} destinataire(s) -> {chemin}\n")
    log.info("Fichiers de classement MX ecrits dans %s", DOSSIER_LISTES_MX)


class ProgressionEnvoi:
    """Suit la progression globale meme quand plusieurs enfants travaillent."""

    def __init__(self, total):
        self.total = max(total, 1)
        self.traites = 0
        self.envoyes = 0
        self.echecs = 0
        self.verrou = threading.Lock()

    def barre(self, pourcentage):
        largeur = 24
        remplis = int((pourcentage / 100) * largeur)
        return "█" * remplis + "░" * (largeur - remplis)

    def enregistrer(self, destinataire, envoye, lot_label):
        with self.verrou:
            self.traites += 1
            if envoye:
                self.envoyes += 1
                statut = "✅ envoye"
            else:
                self.echecs += 1
                statut = "❌ echec"

            pourcentage = (self.traites / self.total) * 100
            log.info(
                "📊 %s %6.2f%% | traites %d/%d | envoyes %d | echecs %d | %s | %s | %s",
                self.barre(pourcentage),
                pourcentage,
                self.traites,
                self.total,
                self.envoyes,
                self.echecs,
                statut,
                lot_label,
                destinataire,
            )


class ControleRythmeGlobal:
    """Coordonne tous les enfants quand l'IP doit etre protegee."""

    def __init__(self):
        self.verrou = threading.Lock()
        self.pause_jusqua = 0
        self.prochain_envoi = 0
        self.mode_securite = False
        self.generation_pause = 0

    def attendre_avant_envoi(self, prefixe):
        """Bloque un enfant tant qu'une pause globale ou un rythme global existe."""
        message_affiche = False
        while True:
            with self.verrou:
                maintenant = time.monotonic()
                attente = max(
                    self.pause_jusqua - maintenant,
                    self.prochain_envoi - maintenant,
                    0,
                )
                if attente <= 0:
                    if self.mode_securite:
                        self.prochain_envoi = max(
                            self.prochain_envoi,
                            maintenant,
                        ) + DELAI_SECURITE_APRES_RATE_LIMIT
                    return self.generation_pause

            if not message_affiche and attente >= 1:
                log.warning("%sPause globale IP active : attente %.0f s avant envoi",
                            prefixe, attente)
                message_affiche = True
            time.sleep(min(attente, 5))

    def signaler_rate_limit(self, etat_mx, destinataire, prefixe):
        """Active la pause globale des qu'un MX signale un rate limit."""
        with self.verrou:
            maintenant = time.monotonic()
            self.pause_jusqua = max(
                self.pause_jusqua,
                maintenant + PAUSE_GLOBALE_APRES_RATE_LIMIT,
            )
            self.prochain_envoi = max(self.prochain_envoi, self.pause_jusqua)
            self.mode_securite = True
            self.generation_pause += 1

        etat_mx["stables_apres_rate_limit"] = 0
        log.warning(
            "%s🛑 Rate limit detecte sur %s (%s) : pause globale %d s, "
            "puis rythme securite %d s entre les envois",
            prefixe,
            etat_mx["mx"],
            destinataire,
            PAUSE_GLOBALE_APRES_RATE_LIMIT,
            DELAI_SECURITE_APRES_RATE_LIMIT,
        )

    def enregistrer_mail_stable(self, etat_mx, prefixe):
        """Relache le mode securite apres assez de mails stables sur un MX."""
        if not self.mode_securite:
            return
        if etat_mx["stables_apres_rate_limit"] < MAILS_STABLES_AVANT_REPRISE_SPEED:
            return

        with self.verrou:
            if not self.mode_securite:
                return
            self.mode_securite = False
            self.prochain_envoi = 0

        decision = (
            f"reprise speed apres {MAILS_STABLES_AVANT_REPRISE_SPEED} mails "
            "sans rate limit"
        )
        etat_mx["derniere_decision"] = decision
        etat_mx["decisions_run"].append(decision)
        log.info("%s✅ %s stable : reprise progressive de la vitesse",
                 prefixe, etat_mx["mx"])


def afficher_bilan_final(heure_debut, heure_fin, duree_secondes, total,
                         reussis, rate_limited_total):
    """Affiche un bilan clair quand le script a fini son travail."""
    echecs = total - reussis
    statut = "TERMINE" if echecs == 0 and not rate_limited_total else "TERMINE AVEC ALERTES"

    log.info("")
    log.info("🧾 ===== BILAN FINAL =====")
    log.info("📍 Fuseau horaire        : Europe/Paris")
    log.info("🕒 Heure de demarrage   : %s", formater_heure(heure_debut))
    log.info("🕘 Heure de fin         : %s", formater_heure(heure_fin))
    log.info("⏱️ Duree totale         : %s", formater_duree(duree_secondes))
    log.info("📬 Mails traites        : %d", total)
    log.info("✅ Mails envoyes        : %d", reussis)
    log.info("❌ Echecs               : %d", echecs)
    log.info("⚠️ Rate limit restants  : %d", len(rate_limited_total))
    log.info("🏁 Statut final         : %s", statut)
    log.info("=========================")


def envoyer_groupe(mx_primaire, destinataires, corps_html, pieces, rate_limited,
                   etat_mx, controle_global, lot_label=None, progression=None):
    """Envoie les mails d'un groupe via une connexion vers le MX.

    - Rejet DEFINITIF (5xx, "user unknown", "relay access denied") -> on passe
      au mail suivant, sans re-essayer.
    - 450 RATE LIMIT -> le mail est garde en memoire dans rate_limited ; on
      coupe la connexion, tout le script marque une pause globale, puis on
      renvoie le mail en rythme securite jusqu'a ce qu'il passe (ou jusqu'a
      MAX_TENTATIVES_RATE_LIMIT).
    """
    prefixe = f"[{lot_label}] " if lot_label else ""
    log.info("%s=== Connexion a %s pour %d destinataire(s), delai %d s, "
             "confiance %d/100, plancher %d s (%s) ===",
             prefixe, mx_primaire, len(destinataires), etat_mx["delai"],
             etat_mx["confiance"], etat_mx["plancher"], etat_mx["source"])
    resultats = {}
    serveur = None
    compteur = 0   # messages envoyes sur la connexion courante
    generation_connexion = 0

    for position, destinataire in enumerate(destinataires, start=1):
        msg = construire_message(destinataire, corps_html, pieces)
        envoye = False
        rejet_definitif = False
        rate_limit_sur_mail = False
        pause_renforce_appliquee = False
        tentative = 0

        while True:
            tentative += 1
            try:
                generation_autorisee = controle_global.attendre_avant_envoi(prefixe)
                if generation_autorisee != generation_connexion:
                    fermer(serveur)
                    serveur = None
                    compteur = 0
                    generation_connexion = generation_autorisee

                # (Re)ouvre la connexion si besoin ou si plafond atteint.
                if serveur is None or compteur >= MAX_PAR_CONNEXION:
                    fermer(serveur)
                    serveur = connecter(mx_primaire)
                    compteur = 0

                envoyer_message_signe(serveur, msg, destinataire)
                compteur += 1
                envoye = True
                log.info("%sOK : %s (tentative %d)", prefixe, destinataire, tentative)

                # Le mail est passe -> on le retire de la memoire de re-essai.
                rate_limited.discard(destinataire)
                break

            except (smtplib.SMTPException, socket.error, OSError) as e:
                # Rejet DEFINITIF (5xx, "user unknown", "relay access denied"...)
                # -> adresse morte : on passe au mail suivant, sans re-essayer.
                if est_rejet_definitif(e):
                    rejet_definitif = True
                    log.error("%sRejet definitif pour %s : %s -> mail suivant",
                              prefixe,
                              destinataire, e)
                    rate_limited.discard(destinataire)
                    if est_adresse_inconnue(e):
                        fermer(serveur)
                        serveur = None
                        compteur = 0
                        pause_renforce_appliquee = True
                        renforcer_mx_apres_adresse_inconnue(
                            etat_mx, destinataire, prefixe
                        )
                    break

                # 450 RATE LIMIT (ou coupure) : on note dans listtemp, on coupe la
                # connexion, on attend, puis on se reconnecte et on renvoie.
                rate_limit_sur_mail = True
                etat_mx["rate_limits"] += 1
                controle_global.signaler_rate_limit(etat_mx, destinataire, prefixe)
                augmenter_delai_mx(etat_mx, prefixe)
                rate_limited.add(destinataire)
                fermer(serveur)
                serveur = None
                compteur = 0

                if tentative >= MAX_TENTATIVES_RATE_LIMIT:
                    log.error("%sAbandon apres %d tentatives : %s reste bloque",
                              prefixe, tentative, destinataire)
                    break

                log.warning("%sRate limit pour %s -> connexion coupee, pause "
                            "globale puis renvoi (tentative %d)",
                            prefixe, destinataire, tentative)

        resultats[destinataire] = envoye
        etat_mx["traites"] += 1
        if envoye:
            etat_mx["envoyes"] += 1
            if not rate_limit_sur_mail:
                memoriser_mail_stable(etat_mx)
                controle_global.enregistrer_mail_stable(etat_mx, prefixe)
                accelerer_mx_si_stable(etat_mx, prefixe)
        else:
            etat_mx["echecs"] += 1

        if RETIRER_EMAIL1_APRES_RESULTAT_FINAL:
            if envoye:
                retirer_destinataires_du_fichier(
                    [destinataire],
                    f"envoye OK via {mx_primaire}",
                )
            elif rejet_definitif:
                retirer_destinataires_du_fichier(
                    [destinataire],
                    f"rejet definitif via {mx_primaire}",
                )
            elif rate_limit_sur_mail:
                log.warning(
                    "%s%s conserve dans %s car bloque par rate limit",
                    prefixe,
                    destinataire,
                    FICHIER_DESTINATAIRES,
                )

        if progression:
            progression.enregistrer(destinataire, envoye, lot_label or mx_primaire)

        # Vitesse : pause courte apres rejet definitif, pause normale apres envoi.
        if position < len(destinataires):
            if pause_renforce_appliquee:
                delai = 0
            else:
                delai = DELAI_APRES_REJET_DEFINITIF if rejet_definitif else etat_mx["delai"]
            if delai > 0:
                time.sleep(delai)

    fermer(serveur)
    return resultats, rate_limited, etat_mx


def envoyer():
    heure_debut = maintenant_paris()
    chrono_debut = time.monotonic()
    log.info("🚀 Demarrage de l'envoi MX direct")
    log.info("🕒 Heure de demarrage : %s", formater_heure(heure_debut))
    mettre_a_jour_spf_avant_envoi()
    afficher_dkim_dns_a_publier()
    verifier_authentification_domaine()

    # Option 1 : destinataires lus depuis le fichier
    destinataires = charger_destinataires(FICHIER_DESTINATAIRES)
    log.info("%d destinataire(s) charge(s) depuis %s", len(destinataires), FICHIER_DESTINATAIRES)

    # Option 2a : corps HTML lu depuis le fichier
    corps_html = charger_html(FICHIER_HTML)

    # Option 2b : pieces jointes lues une fois depuis le dossier
    pieces = charger_pieces_jointes()
    if pieces:
        log.info("%d piece(s) jointe(s) sera(ont) ajoutee(s) a chaque mail.", len(pieces))
    else:
        log.info("Aucune piece jointe.")

    # ETAPE 1 : verification MX + filtre fournisseur + regroupement par MX.
    filtres = filtres_mx_actifs()
    if filtres:
        log.info("Mode filtre OVH actif : on ne garde QUE les MX contenant %s "
                 "(le reste est supprime).", filtres)
    else:
        log.info("Mode tous MX actif : tous les destinataires avec MX valide "
                 "sont retenus.")
    log.info("Verification des domaines et regroupement par serveur MX ...")
    groupes, supprimes = grouper_par_serveur_mx(destinataires)

    if supprimes:
        log.info("%d adresse(s) SUPPRIMEE(S) de la liste :", len(supprimes))
        for adr, raison in supprimes:
            log.info("   - %s (%s)", adr, raison)
        retirer_supprimes_du_fichier(supprimes)

    if not groupes:
        log.error("Aucun destinataire a envoyer apres verification MX. Arret.")
        heure_fin = maintenant_paris()
        afficher_bilan_final(
            heure_debut, heure_fin, time.monotonic() - chrono_debut, 0, 0, set()
        )
        sys.exit(1)

    ecrire_fichiers_par_mx(groupes)

    delais_mx, sources_mx, memoires_mx = charger_delais_mx()
    etats_mx = {}
    lots = []
    for mx_primaire, adresses in groupes.items():
        etat_mx = creer_etat_mx(mx_primaire, delais_mx, sources_mx, memoires_mx)
        etats_mx[mx_primaire] = etat_mx
        lots.append((mx_primaire, adresses, mx_primaire, etat_mx))

    retenus = sum(len(a) for a in groupes.values())
    log.info("-> %d destinataire(s) retenu(s), %d serveur(s) MX, %d enfant(s) possible(s).",
             retenus, len(groupes), len(lots))
    for mx, adresses in groupes.items():
        log.info("   [%s] : %d destinataire(s), delai %d s, confiance %d/100, "
                 "plancher %d s (%s)",
                 mx, len(adresses), etats_mx[mx]["delai"],
                 etats_mx[mx]["confiance"], etats_mx[mx]["plancher"],
                 etats_mx[mx]["source"])

    rate_limited_total = set()
    ecrire_listtemp(rate_limited_total)   # part d'un listtemp propre
    resultats = {}
    progression = ProgressionEnvoi(retenus)
    controle_global = ControleRythmeGlobal()

    nb_enfants = min(len(lots), NB_ENFANTS_MAX)

    if MODE_PARALLELE and nb_enfants > 1:
        log.info("Mode parent/enfants actif : 1 enfant par MX, %d enfant(s) lance(s).",
                 nb_enfants)
        with ThreadPoolExecutor(max_workers=nb_enfants) as executer:
            futures = {
                executer.submit(
                    envoyer_groupe, mx_primaire, adresses, corps_html, pieces,
                    set(), etat_mx, controle_global, lot_label, progression
                ): (lot_label, adresses, etat_mx)
                for mx_primaire, adresses, lot_label, etat_mx in lots
            }
            for future in as_completed(futures):
                lot_label, adresses, etat_mx = futures[future]
                try:
                    resultats_lot, bloque_lot, etat_final = future.result()
                except Exception as e:
                    log.exception("Lot %s en echec inattendu : %s", lot_label, e)
                    for adresse in adresses:
                        resultats[adresse] = False
                    etat_mx["echecs"] += len(adresses)
                    etat_final = etat_mx
                    continue
                resultats.update(resultats_lot)
                rate_limited_total.update(bloque_lot)
                etats_mx[etat_final["mx"]] = etat_final
                ecrire_listtemp(rate_limited_total)
    else:
        log.info("Mode sequentiel : %d serveur(s) MX.", len(lots))
        for mx_primaire, adresses, lot_label, etat_mx in lots:
            resultats_lot, bloque_lot, etat_final = envoyer_groupe(
                mx_primaire, adresses, corps_html, pieces, set(), etat_mx,
                controle_global, lot_label, progression
            )
            resultats.update(resultats_lot)
            rate_limited_total.update(bloque_lot)
            etats_mx[etat_final["mx"]] = etat_final
            ecrire_listtemp(rate_limited_total)

    afficher_bilan_delais_mx(etats_mx)
    sauvegarder_delais_mx(etats_mx)

    # Bilan
    reussis = sum(1 for ok in resultats.values() if ok)
    total = len(resultats)
    log.info("===== DETAILS : %d/%d mail(s) envoye(s) =====", reussis, total)
    for adresse, ok in resultats.items():
        log.info("  %s -> %s", adresse, "OK" if ok else "ECHEC")

    if rate_limited_total:
        log.warning("%d mail(s) encore bloque(s) par le rate limit, listes dans %s.",
                    len(rate_limited_total), LISTTEMP)
    else:
        log.info("Tout est passe : %s est vide.", LISTTEMP)

    heure_fin = maintenant_paris()
    duree_secondes = time.monotonic() - chrono_debut
    afficher_bilan_final(
        heure_debut, heure_fin, duree_secondes, total, reussis,
        rate_limited_total
    )

    if reussis < total:
        sys.exit(1)


if __name__ == "__main__":
    envoyer()
