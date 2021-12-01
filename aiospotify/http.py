# Future
from __future__ import annotations

# Standard Library
import asyncio
import base64
import json
import logging
import urllib.parse
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeVar

# Packages
import aiohttp

# My stuff
from aiospotify import exceptions, objects, utils, values
from aiospotify.typings.objects import (
    AlbumData,
    ArtistData,
    ArtistRelatedArtistsData,
    ArtistTopTracksData,
    AudioFeaturesData,
    AvailableMarketsData,
    CategoryData,
    CategoryPlaylistsData,
    EpisodeData,
    FeaturedPlaylistsData,
    ImageData,
    MultipleAlbumsData,
    MultipleArtistsData,
    MultipleCategoriesData,
    MultipleEpisodesData,
    MultipleShowsData,
    MultipleTracksData,
    NewReleasesData,
    PagingObjectData,
    PlaylistData,
    RecommendationData,
    RecommendationGenresData,
    SearchResultData,
    SeveralAudioFeaturesData,
    ShowData,
    TrackData,
    UserData,
)


if TYPE_CHECKING:

    # My stuff
    from aiospotify.typings import Credentials, OptionalCredentials


__all__ = (
    "Route",
    "HTTPClient"
)

__log__: logging.Logger = logging.getLogger("aiospotify.http")

HTTPMethod = Literal["GET", "POST", "DELETE", "PATCH", "PUT"]
ID = TypeVar("ID", bound=str)


class Route:

    BASE_URL: ClassVar[str] = f"https://api.spotify.com/v1"

    def __init__(
        self,
        method: HTTPMethod,
        path: str,
        /,
        **parameters: Any
    ) -> None:

        self.method: HTTPMethod = method
        self.path: str = path

        url = self.BASE_URL + self.path
        if parameters:
            url = url.format_map({key: urllib.parse.quote(value) if isinstance(value, str) else value for key, value in parameters.items()})

        self.url: str = url

    def __repr__(self) -> str:
        return f"<aiospotify.Route method={self.method} url={self.url}>"


class HTTPClient:

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        session: aiohttp.ClientSession | None
    ) -> None:

        self._client_id: str = client_id
        self._client_secret: str = client_secret
        self._session: aiohttp.ClientSession | None = session

        self._client_credentials: objects.ClientCredentials | None = None

    def __repr__(self) -> str:
        return "<aiospotify.HTTPClient>"

    #

    async def _ensure_session_exists(self) -> None:

        if self._session and not self._session.closed:
            return

        self._session = aiohttp.ClientSession()

    async def _get_credentials(self, credentials: OptionalCredentials) -> Credentials:

        if not self._client_credentials:
            self._client_credentials = await objects.ClientCredentials.from_client_secret(
                self._client_id,
                self._client_secret,
                session=self._session
            )

        _credentials = credentials or self._client_credentials

        if _credentials.is_expired():
            await _credentials.refresh(session=self._session)

        return _credentials

    #

    async def close(self) -> None:

        if not self._session or self._session.closed:
            return

        await self._session.close()
        self._session = None

    async def request(
        self,
        route: Route,
        /,
        *,
        credentials: OptionalCredentials,
        parameters: dict[str, Any] | None = None,
        data: Any = None,
    ) -> Any:

        await self._ensure_session_exists()
        assert self._session is not None

        credentials = await self._get_credentials(credentials)

        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {credentials.access_token}"
        }

        for tries in range(3):

            try:

                async with self._session.request(
                        method=route.method,
                        url=route.url,
                        headers=headers,
                        params=parameters,
                        data=json.dumps(data) if data else None
                ) as response:

                    response_data = await utils.json_or_text(response)

                    if 200 <= response.status < 300:

                        __log__.debug(f"{route.method} @ {route.url} received payload: {response_data}")
                        return response_data

                    if response.status == 413:  # Special case as spotify doesn't return a json content type for this error???
                        raise exceptions.RequestEntityTooLarge(response=response, data={"status": 413, "message": "Request entity too large."})

                    if response.status == 429:  # Retry request after returned amount of time has passed.
                        retry_after = float(response.headers["Retry-After"])
                        __log__.warning(f"{route.method} @ {route.url} is being ratelimited, retrying in {retry_after:.2f} seconds.")
                        await asyncio.sleep(retry_after)
                        __log__.debug(f"{route.method} @ {route.url} is done sleeping for ratelimit, retrying...")
                        continue

                    if response.status in {500, 502, 503}:  # Retry request after a delay.
                        await asyncio.sleep(1 + tries * 2)
                        continue

                    if error := response_data.get("error"):
                        raise values.EXCEPTION_MAPPING[response.status](response, error)

            except OSError as error:
                if tries < 4 and error.errno in (54, 10054):
                    await asyncio.sleep(1 + tries * 2)
                    continue
                raise

        if response:
            raise exceptions.HTTPError(response, response_data["error"])

        raise RuntimeError("This shouldn't happen.")

    # ALBUMS API

    async def get_album(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> AlbumData:

        parameters = {"market": market} if market else None
        return await self.request(Route("GET", "/albums/{id}", id=_id), parameters=parameters, credentials=credentials)

    async def get_albums(
        self,
        ids: Sequence[str],
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> MultipleAlbumsData:

        if len(ids) > 20:
            raise ValueError("'ids' can not contain more than 20 ids.")

        parameters = {"ids": ",".join(ids)}
        if market:
            parameters["market"] = market

        return await self.request(Route("GET", "/albums"), parameters=parameters, credentials=credentials)

    async def get_album_tracks(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> PagingObjectData:

        parameters = {}
        if market:
            parameters["market"] = market
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/albums/{id}/tracks", id=_id), parameters=parameters, credentials=credentials)

    async def get_saved_albums(
        self,
        *,
        market: str | None,
        limit: int | None,
        offset: int | None,
        credentials: Credentials,
    ) -> PagingObjectData:

        parameters = {}
        if market:
            parameters["market"] = market
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/me/albums"), parameters=parameters, credentials=credentials)

    async def save_albums(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("PUT", "/me/albums"), parameters=parameters, credentials=credentials)

    async def remove_albums(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("DELETE", "/me/albums"), parameters=parameters, credentials=credentials)

    async def check_saved_albums(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> list[bool]:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("GET", "/me/albums/contains"), parameters=parameters, credentials=credentials)

    async def get_new_releases(
        self,
        *,
        country: str | None,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> NewReleasesData:

        parameters = {}
        if country:
            parameters["country"] = country
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/browse/new-releases"), parameters=parameters, credentials=credentials)

    # ARTISTS API

    async def get_artist(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> ArtistData:

        parameters = {"market": market} if market else None
        return await self.request(Route("GET", "/artists/{id}", id=_id), parameters=parameters, credentials=credentials)

    async def get_artists(
        self,
        ids: Sequence[str],
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> MultipleArtistsData:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        if market:
            parameters["market"] = market

        return await self.request(Route("GET", "/artists"), parameters=parameters, credentials=credentials)

    async def get_artist_albums(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        limit: int | None,
        offset: int | None,
        include_groups: Sequence[objects.IncludeGroup] | None,
        credentials: OptionalCredentials = None,
    ) -> PagingObjectData:

        parameters = {}
        if market:
            parameters["market"] = market
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset
        if include_groups:
            parameters["include_groups"] = ",".join(include_group.value for include_group in include_groups)

        return await self.request(Route("GET", "/artists/{id}/albums", id=_id), parameters=parameters, credentials=credentials)

    async def get_artist_top_tracks(
        self,
        _id: str,
        /,
        *,
        market: str,
        credentials: OptionalCredentials = None,
    ) -> ArtistTopTracksData:

        parameters = {"market": market}
        return await self.request(Route("GET", "/artists/{id}/top-tracks", id=_id), parameters=parameters, credentials=credentials)

    async def get_related_artists(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> ArtistRelatedArtistsData:

        parameters = {"market": market} if market else None
        return await self.request(Route("GET", "/artists/{id}/related-artists", id=_id), parameters=parameters, credentials=credentials)

    # SHOWS API

    async def get_show(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> ShowData:

        parameters = {"market": market} if market else None
        return await self.request(Route("GET", "/shows/{id}", id=_id), parameters=parameters, credentials=credentials)

    async def get_shows(
        self,
        ids: Sequence[str],
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> MultipleShowsData:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        if market:
            parameters["market"] = market

        return await self.request(Route("GET", "/shows"), parameters=parameters, credentials=credentials)

    async def get_show_episodes(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> PagingObjectData:

        parameters = {}
        if market:
            parameters["market"] = market
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/shows/{id}/episodes", id=_id), parameters=parameters, credentials=credentials)

    async def get_saved_shows(
        self,
        *,
        limit: int | None,
        offset: int | None,
        credentials: Credentials,
    ) -> PagingObjectData:

        parameters = {}
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/me/shows"), parameters=parameters, credentials=credentials)

    async def save_shows(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("PUT", "/me/shows"), parameters=parameters, credentials=credentials)

    async def remove_shows(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("DELETE", "/me/shows"), parameters=parameters, credentials=credentials)

    async def check_saved_shows(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> list[bool]:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("GET", "/me/shows/contains"), parameters=parameters, credentials=credentials)

    # EPISODE API

    async def get_episode(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> EpisodeData:

        parameters = {"market": market} if market else None
        return await self.request(Route("GET", "/episodes/{id}", id=_id), parameters=parameters, credentials=credentials)

    async def get_episodes(
        self,
        ids: Sequence[str],
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> MultipleEpisodesData:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        if market:
            parameters["market"] = market

        return await self.request(Route("GET", "/episodes"), parameters=parameters, credentials=credentials)

    async def get_saved_episodes(
        self,
        *,
        market: str | None,
        limit: int | None,
        offset: int | None,
        credentials: Credentials,
    ) -> PagingObjectData:

        parameters = {}
        if market:
            parameters["market"] = market
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/me/episodes"), parameters=parameters, credentials=credentials)

    async def save_episodes(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("PUT", "/me/episodes"), parameters=parameters, credentials=credentials)

    async def remove_episodes(
        self,
        ids: list[str],
        /,
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("DELETE", "/me/episodes"), parameters=parameters, credentials=credentials)

    async def check_saved_episodes(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> list[bool]:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("GET", "/me/episodes/contains"), parameters=parameters, credentials=credentials)

    # TRACKS API

    async def get_track(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> TrackData:

        parameters = {"market": market} if market else None
        return await self.request(Route("GET", "/tracks/{id}", id=_id), parameters=parameters, credentials=credentials)

    async def get_tracks(
        self,
        ids: Sequence[str],
        *,
        market: str | None,
        credentials: OptionalCredentials = None,
    ) -> MultipleTracksData:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        if market:
            parameters["market"] = market

        return await self.request(Route("GET", "/tracks"), parameters=parameters, credentials=credentials)

    async def get_saved_tracks(
        self,
        *,
        market: str | None,
        limit: int | None,
        offset: int | None,
        credentials: Credentials,
    ) -> PagingObjectData:

        parameters = {}
        if market:
            parameters["market"] = market
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/me/tracks"), parameters=parameters, credentials=credentials)

    async def save_tracks(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("PUT", "/me/tracks"), parameters=parameters, credentials=credentials)

    async def remove_tracks(
        self,
        ids: list[str],
        /,
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("DELETE", "/me/tracks"), parameters=parameters, credentials=credentials)

    async def check_saved_tracks(
        self,
        ids: list[ID],
        /,
        *,
        credentials: Credentials,
    ) -> list[bool]:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("GET", "/me/tracks/contains"), parameters=parameters, credentials=credentials)

    async def get_track_audio_features(
        self,
        _id: str,
        /,
        *,
        credentials: OptionalCredentials = None,
    ) -> AudioFeaturesData:
        return await self.request(Route("GET", "/audio-features/{id}", id=_id), credentials=credentials)

    async def get_several_tracks_audio_features(
        self,
        ids: Sequence[str],
        *,
        credentials: OptionalCredentials = None,
    ) -> SeveralAudioFeaturesData:

        if len(ids) > 100:
            raise ValueError("'ids' can not contain more than 100 ids.")

        parameters = {"ids": ",".join(ids)}
        return await self.request(Route("GET", "/audio-features"), parameters=parameters, credentials=credentials)

    async def get_track_audio_analysis(
        self,
        _id: str,
        /,
        *,
        credentials: OptionalCredentials = None,
    ) -> dict[str, Any]:
        return await self.request(Route("GET", "/audio-analysis/{id}", id=_id), credentials=credentials)

    async def get_recommendations(
        self,
        *,
        seed_artist_ids: Sequence[str] | None,
        seed_genres: Sequence[str] | None,
        seed_track_ids: Sequence[str] | None,
        limit: int | None,
        market: str | None,
        credentials: OptionalCredentials = None,
        **kwargs: int
    ) -> RecommendationData:

        seeds = len([seed for seeds in [seed_artist_ids or [], seed_genres or [], seed_track_ids or []] for seed in seeds])
        if seeds < 1 or seeds > 5:
            raise ValueError("too many or no seed values provided. min 1, max 5.")

        parameters = {}
        if seed_artist_ids:
            parameters["seed_artists"] = ",".join(seed_artist_ids)
        if seed_genres:
            parameters["seed_genres"] = ",".join(seed_genres)
        if seed_track_ids:
            parameters["seed_tracks"] = ",".join(seed_track_ids)

        for key, value in kwargs.items():
            if key not in values.VALID_SEED_KWARGS:
                raise ValueError(f"'{key}' is not a valid kwarg.")
            parameters[key] = value

        if limit:
            utils.limit_value("limit", limit, 1, 100)
            parameters["limit"] = limit
        if market:
            parameters["market"] = market

        return await self.request(Route("GET", "/recommendations"), parameters=parameters, credentials=credentials)

    # SEARCH API

    async def search(
        self,
        query: str,
        /,
        *,
        search_types: Sequence[objects.SearchType],
        include_external: bool = False,
        market: str | None,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> SearchResultData:

        parameters: dict[str, Any] = {
            "q": query.replace(" ", "+"),
            "type": ",".join(search_type.value for search_type in search_types)
        }

        if include_external:
            parameters["include_external"] = "audio"
        if market:
            parameters["market"] = market
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/search"), parameters=parameters, credentials=credentials)

    # USERS API

    async def get_current_user_profile(
        self,
        *,
        credentials: Credentials,
    ) -> UserData:
        return await self.request(Route("GET", "/me"), credentials=credentials)

    async def get_current_user_top_artists(
        self,
        *,
        limit: int | None,
        offset: int | None,
        time_range: objects.TimeRange | None,
        credentials: Credentials,
    ) -> PagingObjectData:

        parameters = {}
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset
        if time_range:
            parameters["time_range"] = time_range.value

        return await self.request(Route("GET", "/me/top/artists"), parameters=parameters, credentials=credentials)

    async def get_current_user_top_tracks(
        self,
        *,
        limit: int | None,
        offset: int | None,
        time_range: objects.TimeRange | None,
        credentials: Credentials,
    ) -> PagingObjectData:

        parameters = {}
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset
        if time_range:
            parameters["time_range"] = time_range.value

        return await self.request(Route("GET", "/me/top/tracks"), parameters=parameters, credentials=credentials)

    async def get_user_profile(
        self,
        _id: str,
        /,
        *,
        credentials: OptionalCredentials = None,
    ) -> UserData:
        return await self.request(Route("GET", "/users/{id}", id=_id), credentials=credentials)

    async def follow_playlist(
        self,
        _id: str,
        /,
        *,
        public: bool | None,
        credentials: Credentials
    ) -> None:

        data = {"public": public} if public else None
        return await self.request(Route("PUT", "playlists/{id}/followers", id=_id), data=data, credentials=credentials)

    async def unfollow_playlist(
        self,
        _id: str,
        /,
        *,
        credentials: Credentials
    ) -> None:
        return await self.request(Route("DELETE", "playlists/{id}/followers", id=_id), credentials=credentials)

    async def check_if_users_follow_playlists(
        self,
        playlist_id: str,
        /,
        *,
        user_ids: list[str],
        credentials: OptionalCredentials = None,
    ) -> None:

        if len(user_ids) > 5:
            raise ValueError("'ids' can not contain more than 5 ids.")

        parameters = {"ids": ",".join(user_ids)}
        route = Route("GET", "/playlists/{playlist_id}/followers/contains", playlist_id=playlist_id)

        return await self.request(route, parameters=parameters, credentials=credentials)

    async def get_followed_users(
        self,
    ) -> None:
        raise exceptions.SpotifyException("This operation is not yet implemented in the spotify api.")

    async def get_followed_artists(
        self,
        *,
        limit: int | None,
        offset: str | None,
        credentials: Credentials,
    ) -> dict[str, Any]:

        parameters: dict[str, Any] = {
            "type": "artist"
        }
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/me/following"), parameters=parameters, credentials=credentials)

    async def follow_users(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {
            "type": "user",
            "ids": ",".join(ids)
        }

        return await self.request(Route("PUT", "/me/following"), parameters=parameters, credentials=credentials)

    async def follow_artists(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {
            "type": "artist",
            "ids": ",".join(ids)
        }

        return await self.request(Route("PUT", "/me/following"), parameters=parameters, credentials=credentials)

    async def unfollow_users(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {
            "type": "user",
            "ids":  ",".join(ids)
        }

        return await self.request(Route("DELETE", "/me/following"), parameters=parameters, credentials=credentials)

    async def unfollow_artists(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> None:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {
            "type": "artist",
            "ids":  ",".join(ids)
        }

        return await self.request(Route("DELETE", "/me/following"), parameters=parameters, credentials=credentials)

    async def check_followed_users(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> list[bool]:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {
            "type": "user",
            "ids":  ",".join(ids)
        }

        return await self.request(Route("GET", "/me/following/contains"), parameters=parameters, credentials=credentials)

    async def check_followed_artists(
        self,
        ids: list[str],
        *,
        credentials: Credentials,
    ) -> list[bool]:

        if len(ids) > 50:
            raise ValueError("'ids' can not contain more than 50 ids.")

        parameters = {
            "type": "artist",
            "ids":  ",".join(ids)
        }

        return await self.request(Route("GET", "/me/following/contains"), parameters=parameters, credentials=credentials)

    # PLAYLISTS API

    async def get_playlist(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        fields: str | None,
        credentials: OptionalCredentials = None,
    ) -> PlaylistData:

        parameters = {
            "additional_types": "track"
        }  # TODO: Support all types
        if market:
            parameters["market"] = market
        if fields:
            parameters["fields"] = fields

        return await self.request(Route("GET", "/playlists/{id}", id=_id), parameters=parameters, credentials=credentials)

    async def change_playlist_details(
        self,
        _id: str,
        /,
        *,
        name: str | None,
        public: bool | None,
        collaborative: bool | None,
        description: str | None,
        credentials: Credentials,
    ) -> None:

        if collaborative and public:
            raise ValueError("collaborative playlists can not be public.")

        data = {}
        if name:
            data["name"] = name
        if public:
            data["public"] = public
        if collaborative:
            data["collaborative"] = collaborative
        if description:
            data["description"] = description

        return await self.request(Route("PUT", "/playlists/{id}", id=_id), data=data, credentials=credentials)

    async def get_playlist_items(
        self,
        _id: str,
        /,
        *,
        market: str | None,
        fields: str | None,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> PagingObjectData:

        parameters: dict[str, Any] = {
            "additional_types": "track"
        }  # TODO: Support all types
        if market:
            parameters["market"] = market
        if fields:
            parameters["fields"] = fields
        if limit:
            utils.limit_value("limit", limit, 1, 100)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/playlists/{id}/tracks", id=_id), parameters=parameters, credentials=credentials)

    async def add_items_to_playlist(
        self,
        _id: str,
        /,
        *,
        uris: Sequence[str],
        position: int | None,
        credentials: Credentials,
    ) -> dict[str, Any]:

        if len(uris) > 100:
            raise ValueError("'uris' can not contain more than 100 URI's.")

        data: dict[str, Any] = {
            "uris": uris
        }
        if position:
            data["position"] = position

        return await self.request(Route("POST", "/playlists/{id}/tracks", id=_id), data=data, credentials=credentials)

    async def reorder_playlist_items(
        self,
        _id: str,
        /,
        *,
        range_start: int,
        insert_before: int,
        range_length: int | None,
        snapshot_id: str | None,
        credentials: Credentials,
    ) -> dict[str, Any]:

        data: dict[str, Any] = {
            "range_start": range_start,
            "insert_before": insert_before
        }
        if range_length:
            data["range_length"] = range_length
        if snapshot_id:
            data["snapshot_id"] = snapshot_id

        return await self.request(Route("PUT", "/playlists/{id}/tracks", id=_id), data=data, credentials=credentials)

    async def replace_playlist_items(
        self,
        _id: str,
        /,
        *,
        uris: Sequence[str],
        credentials: Credentials,
    ) -> None:

        if len(uris) > 100:
            raise ValueError("'uris' can not contain more than 100 URI's.")

        data = {"uris": uris}
        return await self.request(Route("PUT", "/playlists/{id}/tracks", id=_id), data=data, credentials=credentials)

    async def remove_items_from_playlist(
        self,
        _id: str,
        /,
        *,
        uris: Sequence[str],
        snapshot_id: str | None,
        credentials: Credentials,
    ) -> dict[str, Any]:

        if len(uris) > 100:
            raise ValueError("'uris' can not contain more than 100 URI's.")

        data: dict[str, Any] = {
            "tracks": [{"uri": uri} for uri in uris]
        }
        if snapshot_id:
            data["snapshot_id"] = snapshot_id

        return await self.request(Route("DELETE", "/playlists/{id}/tracks", id=_id), data=data, credentials=credentials)

    async def get_current_user_playlists(
        self,
        *,
        limit: int | None,
        offset: int | None,
        credentials: Credentials,
    ) -> PagingObjectData:

        parameters = {}
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/me/playlists"), parameters=parameters, credentials=credentials)

    async def get_user_playlists(
        self,
        _id: str,
        /,
        *,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> PagingObjectData:

        parameters = {}
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/users/{id}/playlists", id=_id), parameters=parameters, credentials=credentials)

    async def create_playlist(
        self,
        *,
        user_id: str,
        name: str,
        public: bool | None,
        collaborative: bool | None,
        description: str | None,
        credentials: Credentials,
    ) -> dict[str, Any]:

        if collaborative and public:
            raise ValueError("collaborative playlists can not be public.")

        data: dict[str, Any] = {
            "name": name
        }
        if public:
            data["public"] = public
        if collaborative:
            data["collaborative"] = collaborative
        if description:
            data["description"] = description

        return await self.request(Route("POST", "/users/{user_id}/playlists", user_id=user_id), data=data, credentials=credentials)

    async def get_featured_playlists(
        self,
        *,
        country: str | None,
        locale: str | None,
        timestamp: str | None,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> FeaturedPlaylistsData:

        parameters = {}
        if country:
            parameters["country"] = country
        if locale:
            parameters["locale"] = locale
        if timestamp:
            parameters["timestamp"] = timestamp
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/browse/featured-playlists"), parameters=parameters, credentials=credentials)

    async def get_category_playlists(
        self,
        _id: str,
        /,
        *,
        country: str | None,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> CategoryPlaylistsData:

        parameters = {}
        if country:
            parameters["country"] = country
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/browse/categories/{id}/playlists", id=_id), parameters=parameters, credentials=credentials)

    async def get_playlist_cover_image(
        self,
        _id: str,
        /,
        *,
        credentials: OptionalCredentials = None,
    ) -> Sequence[ImageData]:
        return await self.request(Route("GET", "/playlists/{id}/images", id=_id), credentials=credentials)

    async def upload_playlist_cover_image(
        self,
        _id: str,
        /,
        *,
        url: str,
        credentials: Credentials,
    ) -> None:

        if not self._session:
            self._session = aiohttp.ClientSession()

        async with self._session.get(url) as request:

            if request.status != 200:
                raise exceptions.SpotifyException("There was a problem while uploading that image.")

            image_bytes = await request.read()
            data = base64.b64encode(image_bytes).decode("utf-8")

        return await self.request(Route("PUT", "/playlists/{id}/images", id=_id), data=data, credentials=credentials)

    # CATEGORY API

    async def get_categories(
        self,
        *,
        country: str | None,
        locale: str | None,
        limit: int | None,
        offset: int | None,
        credentials: OptionalCredentials = None,
    ) -> MultipleCategoriesData:

        parameters = {}
        if country:
            parameters["country"] = country
        if locale:
            parameters["locale"] = locale
        if limit:
            utils.limit_value("limit", limit, 1, 50)
            parameters["limit"] = limit
        if offset:
            parameters["offset"] = offset

        return await self.request(Route("GET", "/browse/categories"), parameters=parameters, credentials=credentials)

    async def get_category(
        self,
        _id: str,
        /,
        *,
        country: str | None,
        locale: str | None,
        credentials: OptionalCredentials = None,
    ) -> CategoryData:

        parameters = {}
        if country:
            parameters["country"] = country
        if locale:
            parameters["locale"] = locale

        return await self.request(Route("GET", "/browse/categories/{id}", id=_id), parameters=parameters, credentials=credentials)

    # GENRE API

    async def get_available_genre_seeds(
        self,
        *,
        credentials: OptionalCredentials = None,
    ) -> RecommendationGenresData:
        return await self.request(Route("GET", "/recommendations/available-genre-seeds"), credentials=credentials)

    # PLAYER API

    async def get_playback_state(
        self,
        *,
        market: str | None,
        credentials: Credentials,
    ) -> dict[str, Any]:

        parameters = {
            "additional_types": "track"
        }  # TODO: Support all types
        if market:
            parameters["market"] = market

        return await self.request(Route("GET", "/me/player"), parameters=parameters, credentials=credentials)

    async def transfer_playback(
        self,
        *,
        device_id: str,
        ensure_playback: bool | None,
        credentials: Credentials,
    ) -> None:

        data: dict[str, Any] = {
            "device_ids": [device_id]
        }
        if ensure_playback:
            data["play"] = ensure_playback

        return await self.request(Route("PUT", "/me/player"), data=data, credentials=credentials)

    async def get_available_devices(
        self,
        *,
        credentials: Credentials,
    ) -> dict[str, Any]:
        return await self.request(Route("GET", "/me/player/devices"), credentials=credentials)

    async def get_currently_playing_track(
        self,
        *,
        market: str | None,
        credentials: Credentials,
    ) -> dict[str, Any]:

        parameters = {
            "additional_types": "track"
        }  # TODO: Support all types
        if market:
            parameters["market"] = market

        return await self.request(Route("GET", "/me/player/currently-playing"), parameters=parameters, credentials=credentials)

    async def start_playback(
        self,
        *,
        device_id: str | None,
        context_uri: str | None,
        uris: list[str] | None,
        offset: int | str | None,
        position_ms: int | None,
        credentials: Credentials,
    ) -> None:

        if context_uri and uris:
            raise ValueError("'context_uri' and 'uris' can not both be specified.")

        parameters = {}
        if device_id:
            parameters["device_id"] = device_id

        data = {}

        if context_uri or uris:

            if context_uri:
                data["context_uri"] = context_uri
            if uris:
                data["uris"] = uris

            if offset:
                data["offset"] = {}
                if isinstance(offset, int):
                    data["offset"]["position"] = offset
                else:
                    data["offset"]["uri"] = offset

            if position_ms:
                data["position_ms"] = position_ms

        return await self.request(Route("PUT", "/me/player/play"), parameters=parameters, data=data, credentials=credentials)

    async def resume_playback(
        self,
        *,
        device_id: str | None,
        offset: int | str | None,
        position_ms: int | None,
        credentials: Credentials,
    ) -> None:

        return await self.start_playback(
            device_id=device_id,
            context_uri=None,
            uris=None,
            offset=offset,
            position_ms=position_ms,
            credentials=credentials
        )

    async def pause_playback(
        self,
        *,
        device_id: str | None,
        credentials: Credentials,
    ) -> None:

        parameters = {}
        if device_id:
            parameters["device_id"] = device_id

        return await self.request(Route("PUT", "/me/player/pause"), parameters=parameters, credentials=credentials)

    async def skip_to_next(
        self,
        *,
        device_id: str | None,
        credentials: Credentials,
    ) -> None:

        parameters = {}
        if device_id:
            parameters["device_id"] = device_id

        return await self.request(Route("POST", "/me/player/next"), parameters=parameters, credentials=credentials)

    async def skip_to_previous(
        self,
        *,
        device_id: str | None,
        credentials: Credentials,
    ) -> None:

        parameters = {}
        if device_id:
            parameters["device_id"] = device_id

        return await self.request(Route("POST", "/me/player/previous"), parameters=parameters, credentials=credentials)

    async def seek_to_position(
        self,
        *,
        position_ms: int,
        device_id: str | None,
        credentials: Credentials,
    ) -> None:

        parameters: dict[str, Any] = {
            "position_ms": position_ms
        }
        if device_id:
            parameters["device_id"] = device_id

        return await self.request(Route("PUT", "/me/player/seek"), parameters=parameters, credentials=credentials)

    async def set_repeat_mode(
        self,
        *,
        repeat_mode: objects.RepeatMode,
        device_id: str | None,
        credentials: Credentials,
    ) -> None:

        parameters = {
            "state": repeat_mode.value
        }
        if device_id:
            parameters["device_id"] = device_id

        return await self.request(Route("PUT", "/me/player/repeat"), parameters=parameters, credentials=credentials)

    async def set_playback_volume(
        self,
        *,
        volume_percent: int,
        device_id: str | None,
        credentials: Credentials,
    ) -> None:

        utils.limit_value("volume_percent", volume_percent, 0, 100)

        parameters: dict[str, Any] = {
            "volume_percent": volume_percent
        }
        if device_id:
            parameters["device_id"] = device_id

        return await self.request(Route("PUT", "/me/player/volume"), parameters=parameters, credentials=credentials)

    async def toggle_playback_shuffle(
        self,
        *,
        state: bool,
        device_id: str | None,
        credentials: Credentials,
    ) -> None:

        parameters: dict[str, Any] = {
            "state": "true" if state else "false"
        }
        if device_id:
            parameters["device_id"] = device_id

        return await self.request(Route("PUT", "/me/player/shuffle"), parameters=parameters, credentials=credentials)

    async def get_recently_played_tracks(
        self,
        *,
        limit: int | None,
        before: int | None,
        after: int | None,
        credentials: Credentials,
    ) -> dict[str, Any]:

        if before and after:
            raise ValueError("'before' and 'after' can not both be specified.")

        parameters = {}
        if limit:
            parameters["limit"] = limit
        if before:
            parameters["before"] = before
        if after:
            parameters["after"] = after

        return await self.request(Route("GET", "/me/player/recently-played"), parameters=parameters, credentials=credentials)

    async def add_item_to_playback_queue(
        self,
        *,
        uri: str,
        device_id: str | None,
        credentials: Credentials,
    ) -> None:

        parameters = {
            "uri": uri
        }
        if device_id:
            parameters["device_id"] = device_id

        return await self.request(Route("POST", "/me/player/queue"), parameters=parameters, credentials=credentials)

    # MARKETS API

    async def get_available_markets(
        self,
        *,
        credentials: OptionalCredentials = None,
    ) -> AvailableMarketsData:
        return await self.request(Route("GET", "/markets"), credentials=credentials)
