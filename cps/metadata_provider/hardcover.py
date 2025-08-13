# -*- coding: utf-8 -*-

#                       Hardcover metadata provider for Autocaliweb.  
#      
# Provides book metadata search functionality using the Hardcover.app GraphQL API.  
# Requires API token configuration in admin settings or user profile.  
#
# Based on:
#    Hardcover metadata provider for Calibre-Web (https://github.com/janeczku/calibre-web)
#    Original Copyright: Copyright (C) 2021 OzzieIsaacs
#    Original License: GNU General Public License v3.0 (GPLv3)
#
# Modifications and adaptation for Autocaliweb:
#    Copyright (C) 2025, Autocaliweb
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

# Hardcover api document: https://docs.hardcover.app/api/getting-started/
from typing import Dict, List, Optional, Union

import requests
from os import getenv

try:
    from cps import logger, config, constants
    from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
    from cps.isoLanguages import get_language_name
    from ..cw_login import current_user
except Exception as e:
    import logging as _logging
    from dataclasses import dataclass, field

    class _FallbackLogger:
        @staticmethod
        def create():
            _log = _logging.getLogger("hardcover")
            if not _log.handlers:
                _h = _logging.StreamHandler()
                _h.setFormatter(_logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
                _log.addHandler(_h)
                _log.setLevel(_logging.INFO)
            return _log
        
    logger = _FallbackLogger()

    class _FallbackConfig:
        config_hardcover_api_token = Optional[str] = None

    config = _FallbackConfig()

    class _FallbackConstants:
        USER_AGENT = "Autocaliweb/Hardcover-Metadata-Provider"
        
    constants = _FallbackConstants()

    @dataclass
    class MetaSourceInfo:
        id: str
        description: str
        link: str

    @dataclass
    class MetaRecord:
        id: Union[str, int]
        title: str
        authors: List[str]
        url: str
        source: MetaSourceInfo
        series: str = ""
        cover: str = ""
        description: Optional[str] = ""
        series: Optional[str] = ""
        series_index: Optional[Union[int, float]] = 0
        identifiers: Dict[str, Union[str, int]] = field(default_factory=dict)
        publisher: Optional[str] = ""
        publishedDate: Optional[str] = ""
        rating: Optional[int] = 0
        languages: Optional[List[str]] = field(default_factory=list)
        tags: Optional[List[str]] = field(default_factory=list)
        format: Optional[str] = None

    class Metadata:
        def __init__(self):
            self.active = True

        def set_status(self, state):
            self.active = state

    def get_language_name(locale: str, code3: str) -> str:
        return code3 or ""
    
    class _DummyUser:
        hardcover_token: Optional[str] = None

    current_user = _DummyUser()

log = logger.create()

class Hardcover(Metadata):
    __name__ = "Hardcover"
    __id__ = "hardcover"
    DESCRIPTION = "Hardcover Books"
    META_URL = "https://hardcover.app"
    BASE_URL = "https://api.hardcover.app/v1/graphql"
    SEARCH_QUERY = """query Search($query: String!) {
        search(query: $query, query_type: "Book", per_page: 50) {
            results
        }
    }
    """
    EDITION_QUERY = """query getEditions($query: Int!) {
        books(
            where: { id: { _eq: $query } }
            order_by: { users_read_count: desc_nulls_last }
        ) {
            title
            slug
            id
            
            book_series {
                series {
                    name
                }
                position
            }
            rating
            editions(
                where: {
                    _or: [{ reading_format_id: { _neq: 2 } }, { edition_format: { _is_null: true } }]
                }
                order_by: [{ reading_format_id: desc_nulls_last },{users_count: desc_nulls_last }]
            ) {
                id
                isbn_13
                isbn_10
                title
                reading_format_id
                contributions {
                    author {
                        name
                    }
                }
                image {
                    url
                }
                language {
                    code3
                }
                publisher {
                    name
                }
                release_date
                
            }
            description
            cached_tags(path: "Genre")
        }
    }
    """
    HEADERS = {
        "Content-Type": "application/json",
        "User-Agent": constants.USER_AGENT,
    }
    FORMATS = ["","Physical Book","","","E-Book"] # Map reading_format_id to text equivelant.

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        val = list()
        if self.active:
            try:
                token = (current_user.hardcover_token or config.config_hardcover_api_token or getenv("HARDCOVER_TOKEN"))
                if not token:
                    self.set_status(False)
                    raise Exception("Hardcover token not set for user, and no global token provided.")
                edition_search = query.split(":")[0] == "hardcover-id"
                Hardcover.HEADERS["Authorization"] = "Bearer %s" % token.replace("Bearer ","")
                result = requests.post(
                    Hardcover.BASE_URL,
                    json={
                        "query":Hardcover.SEARCH_QUERY if not edition_search else Hardcover.EDITION_QUERY,
                        "variables":{
                            "query":
                            query if not edition_search else query.split(":")[1]
                        }
                    },
                    headers=Hardcover.HEADERS,
                )
                result.raise_for_status()
                response_data = result.json()
                
                # Check for GraphQL errors  
                if "errors" in response_data:  
                    log.error(f"GraphQL errors: {response_data['errors']}")  
                    return []
                    
                # Validate response structure  
                if "data" not in response_data:  
                    log.warning("Invalid response structure: missing 'data' field")  
                    return []  

            except requests.exceptions.RequestException as e:  
                log.warning(f"HTTP request failed: {e}")  
                return []  
            except ValueError as e:  
                log.warning(f"JSON parsing failed: {e}")  
                return []  
            except Exception as e:
                log.warning(f"Unexpected error: {e}")
                return [] # Return empty list instead of None

            # Process results with error handling
            try:
                if edition_search:
                    books_data = self._safe_get(response_data, "data", "books", default=[])
                    if books_data:
                        result = books_data[0]
                        val = self._parse_edition_results(result=result, generic_cover=generic_cover, locale=locale)
                else:
                    raw_results = self._safe_get(response_data, "data", "search", "results", "hits", default=[])
                    
                    try:
                        if isinstance(raw_results, str):
                            import json as _json
                            parsed = _json.loads(raw_results)
                        else:
                            parsed = raw_results
                    except Exception as _:
                        parsed = []

                    search_hits = self._safe_get(parsed, "hits", default=[])

                    for result in search_hits:
                        match = self._parse_title_result(
                            result=result, generic_cover=generic_cover, locale=locale
                        )
                        if match:  # Only add valid results
                            val.append(match)
            except Exception as e:
                log.warning(f"Error processing results: {e}")
                return []

        return val

    def _parse_title_result(
        self, result: Dict, generic_cover: str, locale: str
    ) -> Optional[MetaRecord]:
        try:
            document = self._safe_get(result, "document", default={})
            if not document:
                return None

            series_info = self._safe_get(document, "featured_series", default={})
            series = self._safe_get(series_info, "series_name", default="")
            series_index = self._safe_get(series_info, "position", default="")

            match = MetaRecord(
                id=self._safe_get(document, "id", default=""),
                title=self._safe_get(document, "title", default=""),
                authors=self._safe_get(document, "author_names", default=[]),
                url=self._parse_title_url(result, ""),
                source=MetaSourceInfo(
                    id=self.__id__,
                    description=Hardcover.DESCRIPTION,
                    link=Hardcover.META_URL,
                ),
                series=series,
            )

            # Safe cover image access
            image_data = self._safe_get(document, "image", default={})
            match.cover = self._safe_get(image_data, "url", default=generic_cover)

            match.description = self._safe_get(document, "description", default="")
            match.publishedDate = self._safe_get(document, "release_date", default="")
            match.series_index = series_index
            match.tags = self._safe_get(document, "genres", default=[])
            match.identifiers = {
                "hardcover-id": match.id,
                "hardcover": self._safe_get(document, "slug", default="")
            }
            return match
        except Exception as e:
            log.warning(f"Error parsing title result: {e}")
            return None

    def _parse_edition_results(
        self, result: Dict, generic_cover: str, locale: str
    ) -> List[MetaRecord]:
        editions = list()
        id = result.get("id","")
        for edition in result["editions"]:
            match = MetaRecord(
                id=id,
                title=edition.get("title",""),
                authors=self._parse_edition_authors(edition,[]),
                url=self._parse_edition_url(result, edition, ""),
                source=MetaSourceInfo(
                    id=self.__id__,
                    description=Hardcover.DESCRIPTION,
                    link=Hardcover.META_URL,
                ),
                series=(result.get("book_series") or [{}])[0].get("series",{}).get("name", ""),
            )
            match.cover = (edition.get("image") or {}).get("url", generic_cover)
            match.description = result.get("description","")
            match.publisher = (edition.get("publisher") or {}).get("name","")
            match.publishedDate = edition.get("release_date", "")
            match.series_index = (result.get("book_series") or [{}])[0].get("position", "")
            match.tags = self._parse_tags(result,[])
            match.languages = self._parse_languages(edition,locale)
            match.identifiers = {
                "hardcover-id": id,
                "hardcover": result.get("slug", ""),
                "hardcover-edition": edition.get("id",""),
                "isbn": (edition.get("isbn_13",edition.get("isbn_10")) or "")
            }
            isbn = edition.get("isbn_13",edition.get("isbn_10"))
            if isbn:
                match.identifiers["isbn"] = isbn
            
            rf_id = edition.get("reading_format_id")
            if isinstance(rf_id, int) and 0 <= rf_id < len(Hardcover.FORMATS):
                match.format = Hardcover.FORMATS[rf_id]
            else:
                match.format = ""
            
            editions.append(match)
        return editions

    @staticmethod
    def _parse_title_url(result: Dict, url: str) -> str:
        # Use safe access instead of direct dictionary access  
        document = result.get("document", {})  
        hardcover_slug = document.get("slug", "")  
        if hardcover_slug:  
            return f"https://hardcover.app/books/{hardcover_slug}"  
        return url


    @staticmethod
    def _parse_edition_url(result: Dict, edition: Dict, url: str) -> str:
        edition = edition.get("id", "")
        slug = result.get("slug","")
        if edition:
            return f"https://hardcover.app/books/{slug}/editions/{edition}"
        return url

    @staticmethod
    def _parse_edition_authors(edition: Dict, authors: List[str]) -> List[str]:
        try:
            contributions = edition.get("contributions", [])
            if not isinstance(contributions, list):
                return authors

            result = []
            for contrib in contributions:
                if isinstance(contrib, dict) and "author" in contrib:
                    author_data = contrib["author"]
                    if isinstance(author_data, dict) and "name" in author_data:
                        result.append(author_data["name"])
            return result if result else authors
        except Exception as e:
            log.warning(f"Error parsing edition authors: {e}")
            return authors

    @staticmethod
    def _parse_tags(result: Dict, tags: List[str]) -> List[str]:
        try:
            cached_tags = result.get("cached_tags", [])
            if not isinstance(cached_tags, list):
                return tags

            result_tags = []
            for item in cached_tags:
                if isinstance(item, dict) and "tag" in item and item["tag"]:
                    result_tags.append(item["tag"])
            return result_tags if result_tags else tags
        except Exception as e:
            log.warning(f"Error parsing tags: {e}")
            return tags

    @staticmethod
    def _parse_languages(edition: Dict, locale: str) -> List[str]:
        language_iso = (edition.get("language") or {}).get("code3","")
        languages = (
            [get_language_name(locale, language_iso)]
            if language_iso
            else []
        )
        return languages

    @staticmethod
    def _safe_get(data, *keys, default=None):
        """Safely get nested dictionary values"""
        try:
            for key in keys:
                if isinstance(data, dict) and key in data:
                    data = data[key]
                else:
                    return default
            return data
        except (TypeError, KeyError):
            return default
        
if __name__ == "__main__":
    import argparse
    import json
    from dataclasses import asdict, is_dataclass

    parser = argparse.ArgumentParser(description="Hardcover Metadata Provider Test")
    parser.add_argument("query", help="Search query for Hardcover metadata, e.g., 'hardcover-id:12345' or text")
    parser.add_argument("--token", dest="token", help="Hardcover API token or set HARDCOVER_TOKEN environment variable")
    parser.add_argument("--locale", default="en", help="Locale for language names (default: 'en')")
    parser.add_argument("--cover", dest="generic_cover", default="", help="Generic cover image URL fallback")
    args = parser.parse_args()

    token = args.token or getenv("HARDCOVER_TOKEN")
    if token:
        try:
            config.config_hardcover_api_token = token
        except Exception:
            pass
    
    class _DummyUser:
        hardcover_token: None

    try:
        globals()["current_user"] = _DummyUser()
    except Exception:
        pass

    provider = Hardcover()
    results = provider.search(query=args.query, generic_cover=args.generic_cover, locale=args.locale) or []

    def _to_dict(obj):
        try:
            if is_dataclass(obj):
                return asdict(obj)
        except Exception:
            pass

        if isinstance(obj, (list, tuple)):
            return [_to_dict(item) for item in obj]
        
        if isinstance(obj, dict):
            return {k: _to_dict(v) for k, v in obj.items()}
        
        return obj
    
    print(json.dumps([_to_dict(result) for result in results], indent=2, ensure_ascii=False))