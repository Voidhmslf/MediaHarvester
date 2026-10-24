import unittest

from src.core.router import detect_url_type, gallery_platform_name


class RouterTests(unittest.TestCase):
    def check(self, url, platform, engine, **flags):
        d = detect_url_type(url)
        self.assertEqual((d["platform"], d["engine"]), (platform, engine), url)
        for key, value in flags.items():
            self.assertEqual(bool(d.get(key)), value, f"{key} for {url}")

    def test_existing_platforms_unchanged(self):
        self.check("https://www.youtube.com/watch?v=abc", "youtube", "ytdlp")
        self.check("https://youtu.be/abc", "youtube", "ytdlp")
        self.check("https://music.youtube.com/watch?v=abc", "youtube", "ytdlp")
        self.check("https://www.instagram.com/p/XYZ/", "instagram", "insta")
        self.check("https://www.instagram.com/reel/XYZ/", "instagram", "ytdlp")
        self.check("https://vk.com/album-1_2", "vk", "vk_photos")
        self.check("https://vk.com/video-1_2", "vk", "ytdlp")
        self.check("https://example.com/video.mp4", "generic", "ytdlp")

    def test_tiktok(self):
        self.check("https://www.tiktok.com/@user/video/123", "tiktok", "ytdlp")
        self.check("https://vm.tiktok.com/ZMabc/", "tiktok", "ytdlp")
        self.check("https://www.tiktok.com/@user/photo/123", "tiktok", "gallery")
        self.check("https://www.tiktok.com/@user", "tiktok", "ytdlp", playlist=True)

    def test_x(self):
        self.check("https://x.com/user/status/123", "x", "ytdlp")
        self.check("https://twitter.com/user/status/123?s=20", "x", "ytdlp")
        self.check("https://x.com/user", "x", "gallery", listing=True)

    def test_pinterest(self):
        self.check("https://www.pinterest.com/pin/123/", "pinterest", "gallery", listing=False)
        self.check("https://ru.pinterest.com/pin/123/", "pinterest", "gallery")
        self.check("https://pin.it/abc", "pinterest", "gallery", listing=False)
        self.check("https://www.pinterest.com/user/board/", "pinterest", "gallery", listing=True)

    def test_reddit(self):
        self.check("https://www.reddit.com/r/pics/comments/abc/title/", "reddit", "ytdlp")
        self.check("https://v.redd.it/abc", "reddit", "ytdlp")
        self.check("https://www.reddit.com/r/pics/", "reddit", "gallery", listing=True)

    def test_soundcloud(self):
        self.check("https://soundcloud.com/artist/track", "soundcloud", "ytdlp", playlist=False)
        self.check("https://soundcloud.com/artist/sets/album", "soundcloud", "ytdlp", playlist=True)
        self.check("https://soundcloud.com/artist", "soundcloud", "ytdlp", playlist=True)
        self.check("soundcloud.com/artist/track", "soundcloud", "ytdlp")

    def test_host_matching_is_not_substring(self):
        self.check("https://notx.com/user/status/1", "generic", "ytdlp")
        self.check("https://example.com/?u=https://x.com/a/status/1", "generic", "ytdlp")

    def test_gallery_platform_name(self):
        self.assertEqual(gallery_platform_name("https://x.com/a/status/1"), "X")
        self.assertEqual(gallery_platform_name("https://www.instagram.com/p/1/"), "Instagram")
        self.assertIsNone(gallery_platform_name("https://youtu.be/abc"))


if __name__ == "__main__":
    unittest.main()
