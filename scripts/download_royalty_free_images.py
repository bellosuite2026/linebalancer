#!/usr/bin/env python3
"""
Script pour télécharger des images libres de droits (royalty-free) 
depuis Unsplash, Pexels, Pixabay pour les machines textiles.
Utilise les APIs publiques (pas de scraping).
"""

import os
import sys
import json
import requests
from pathlib import Path
from typing import Dict, List, Optional

# Configuration des APIs
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY")  # Nécessite une clé gratuite sur unsplash.com/developers
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")  # Nécessite une clé gratuite sur pexels.com/api
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY")  # Nécessite une clé gratuite sur pixabay.com/api/docs/

# Mots-clés de recherche par type de machine
SEARCH_TERMS = {
    "piqueuse_plate": [
        "industrial sewing machine",
        "flatlock sewing machine",
        "garment factory sewing",
        "single needle lockstitch"
    ],
    "piqueuse_2_aiguilles": [
        "double needle sewing machine",
        "twin needle industrial sewing",
        "two needle lockstitch"
    ],
    "surjeteuse_3_fils": [
        "overlock machine 3 thread",
        "serger machine industrial",
        "3 thread overlock"
    ],
    "surjeteuse_4_fils": [
        "overlock machine 4 thread",
        "4 thread serger industrial",
        "4 thread overlock machine"
    ],
    "surjeteuse_5_fils": [
        "5 thread overlock machine",
        "safety stitch overlock",
        "5 thread serger industrial"
    ],
    "piqueuse_boutonniere": [
        "buttonhole machine industrial",
        "automatic buttonhole machine",
        "industrial buttonhole sewing"
    ],
    "piqueuse_bouton": [
        "button sewing machine industrial",
        "automatic button attaching machine",
        "button attacher industrial"
    ],
    "piqueuse_ourlet": [
        "hemming machine industrial",
        "blind stitch machine",
        "hemmer industrial sewing"
    ],
    "piqueuse_galon": [
        "tape binding machine industrial",
        "elastic attaching machine",
        "binding machine sewing"
    ],
    "presse_vapeur": [
        "steam press industrial",
        "steam ironing press",
        "garment steam press"
    ],
    "repasseuse_tunnel": [
        "tunnel finisher industrial",
        "garment tunnel finisher",
        "steam tunnel finisher"
    ],
    "table_controle": [
        "quality control table textile",
        "inspection table garment",
        "fabric inspection table"
    ],
    "table_travail": [
        "cutting table textile",
        "work table garment factory",
        "pattern making table"
    ]
}

# Dossier de sortie
OUTPUT_DIR = Path(__file__).parent.parent / "gui" / "assets" / "machines" / "photos"

def create_output_dirs():
    """Crée les dossiers de sortie"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for machine_type in SEARCH_TERMS.keys():
        (OUTPUT_DIR / machine_type).mkdir(exist_ok=True)

def download_unsplash(query: str, machine_type: str, count: int = 3) -> List[Dict]:
    """Télécharge depuis Unsplash (nécessite UNSPLASH_ACCESS_KEY)"""
    if not UNSPLASH_ACCESS_KEY:
        return []
    
    url = "https://api.unsplash.com/search/photos"
    params = {
        "query": query,
        "per_page": count,
        "orientation": "landscape",
        "content_filter": "high"
    }
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for i, photo in enumerate(data.get("results", [])):
            img_url = photo["urls"]["regular"]
            photographer = photo["user"]["name"]
            photo_id = photo["id"]
            
            results.append({
                "source": "unsplash",
                "query": query,
                "image_url": img_url,
                "photographer": photographer,
                "photo_id": photo_id,
                "license": "Unsplash License (free commercial use)",
                "attribution": f"Photo by {photographer} on Unsplash"
            })
        return results
    except Exception as e:
        print(f"⚠️  Erreur Unsplash pour '{query}': {e}")
        return []

def download_pexels(query: str, machine_type: str, count: int = 3) -> List[Dict]:
    """Télécharge depuis Pexels (nécessite PEXELS_API_KEY)"""
    if not PEXELS_API_KEY:
        return []
    
    url = "https://api.pexels.com/v1/search"
    params = {
        "query": query,
        "per_page": count,
        "orientation": "landscape",
        "size": "large"
    }
    headers = {"Authorization": PEXELS_API_KEY}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for photo in data.get("photos", []):
            img_url = photo["src"]["large2x"]
            photographer = photo["photographer"]
            photo_id = photo["id"]
            
            results.append({
                "source": "pexels",
                "query": query,
                "image_url": img_url,
                "photographer": photographer,
                "photo_id": photo_id,
                "license": "Pexels License (free commercial use)",
                "attribution": f"Photo by {photographer} on Pexels"
            })
        return results
    except Exception as e:
        print(f"⚠️  Erreur Pexels pour '{query}': {e}")
        return []

def download_pixabay(query: str, machine_type: str, count: int = 3) -> List[Dict]:
    """Télécharge depuis Pixabay (nécessite PIXABAY_API_KEY)"""
    if not PIXABAY_API_KEY:
        return []
    
    url = "https://pixabay.com/api/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "image_type": "photo",
        "orientation": "horizontal",
        "per_page": count,
        "safesearch": "true",
        "order": "popular"
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        for hit in data.get("hits", []):
            img_url = hit["largeImageURL"]
            photographer = hit["user"]
            photo_id = hit["id"]
            
            results.append({
                "source": "pixabay",
                "query": query,
                "image_url": img_url,
                "photographer": photographer,
                "photo_id": photo_id,
                "license": "Pixabay License (free commercial use)",
                "attribution": f"Image by {photographer} from Pixabay"
            })
        return results
    except Exception as e:
        print(f"⚠️  Erreur Pixabay pour '{query}': {e}")
        return []

def download_image(url: str, save_path: Path) -> bool:
    """Télécharge une image et la sauvegarde"""
    try:
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()
        
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"❌ Erreur téléchargement {save_path}: {e}")
        return False

def download_all_machines():
    """Télécharge les images pour tous les types de machines"""
    create_output_dirs()
    
    print("📥 Téléchargement des images libres de droits pour machines textiles...")
    print("=" * 60)
    
    if not any([UNSPLASH_ACCESS_KEY, PEXELS_API_KEY, PIXABAY_API_KEY]):
        print("⚠️  Aucune clé API configurée !")
        print("   Configurez au moins une de ces variables d'environnement :")
        print("   - UNSPLASH_ACCESS_KEY (gratuit sur unsplash.com/developers)")
        print("   - PEXELS_API_KEY (gratuit sur pexels.com/api)")
        print("   - PIXABAY_API_KEY (gratuit sur pixabay.com/api/docs/)")
        print()
        print("   Pour l'instant, utilisez les SVG vectoriels fournis.")
        return
    
    total_downloaded = 0
    
    for machine_type, queries in SEARCH_TERMS.items():
        print(f"\n🔧 {machine_type}")
        machine_dir = OUTPUT_DIR / machine_type
        
        for query in queries:
            all_results = []
            
            # Essayer chaque API
            if UNSPLASH_ACCESS_KEY:
                all_results.extend(download_unsplash(query, machine_type))
            if PEXELS_API_KEY:
                all_results.extend(download_pexels(query, machine_type))
            if PIXABAY_API_KEY:
                all_results.extend(download_pixabay(query, machine_type))
            
            if not all_results:
                continue
            
            # Télécharger les images
            for i, result in enumerate(all_results[:2]):  # Max 2 par requête
                ext = ".jpg"
                filename = f"{machine_type}_{result['source']}_{result.get('photo_id', i)}{ext}"
                save_path = machine_dir / filename
                
                if save_path.exists():
                    print(f"   ✅ Existe déjà: {filename}")
                    continue
                
                if download_image(result["image_url"], save_path):
                    # Sauvegarder les métadonnées
                    meta_path = save_path.with_suffix(".json")
                    meta = {
                        "machine_type": machine_type,
                        "search_query": query,
                        "source": result["source"],
                        "photographer": result.get("photographer", "Unknown"),
                        "photo_id": result.get("photo_id", ""),
                        "license": result["license"],
                        "attribution": result["attribution"],
                        "original_url": result["image_url"]
                    }
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2, ensure_ascii=False)
                    
                    print(f"   ✅ Téléchargé: {filename} ({result['source']})")
                    total_downloaded += 1
    
    print(f"\n✅ Terminé ! {total_downloaded} images téléchargées dans {OUTPUT_DIR}")
    print("\n📝 Note: Ces images sont sous licences libres (Unsplash/Pexels/Pixabay)")
    print("   Vérifiez les attributions dans les fichiers .json correspondants.")

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(__doc__)
        return
    download_all_machines()

if __name__ == "__main__":
    main()