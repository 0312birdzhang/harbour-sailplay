"""Optional Content1 presentation hints: images, playback status and layouts."""
import unittest

from sailplay_sdk.content_model import (clean_presentation, content_item, content_page, merge_content,
                                        split_content, validate_content)
from sailplay_sdk.model import Fault


def rows():
    return [content_item('a', 'Episode 1', kind='action', action='play', parameters={'n': 1},
                         image='/home/defaultuser/.cache/app/a.png', playback='playing'),
            content_item('b', 'Episode 2', kind='action', action='play', image='https://example.org/b.jpg'),
            content_item('c', 'Archive', playback='finished'),
            content_item('d', 'Plain')]


class PresentationTests(unittest.TestCase):
    def test_a_page_without_hints_is_exactly_a_content1_page(self):
        page = content_page(items=[content_item('d', 'Plain')])
        self.assertEqual(validate_content(page), page)
        self.assertEqual(split_content(page), (page, {}))

    def test_hints_travel_beside_a_strict_page(self):
        page, presentation = split_content(content_page(items=rows(), layout='grid'))
        self.assertEqual(validate_content(page), page)
        self.assertTrue(all(set(item) == {'id', 'title', 'subtitle', 'kind', 'action', 'parameters', 'enabled'}
                            for item in page['items']))
        self.assertEqual(presentation, {'layout': 'grid', 'items': {
            'a': {'image': '/home/defaultuser/.cache/app/a.png', 'playback': 'playing'},
            'b': {'image': 'https://example.org/b.jpg'},
            'c': {'playback': 'finished'}}})

    def test_tabs_and_wide_cards(self):
        folders = [content_item('new', 'New'), content_item('all', 'All')]
        rich = content_page(items=folders, layout='wide', tabs=True)
        page, presentation = split_content(rich)
        self.assertEqual(presentation, {'layout': 'wide', 'tabs': True})
        self.assertEqual(merge_content(page, presentation), rich)
        self.assertNotIn('tabs', content_page(items=folders, tabs=False))
        with self.assertRaises(Fault):
            content_page(items=folders, tabs='yes')
        self.assertEqual(merge_content(page, {'tabs': 1, 'layout': ['grid']}), page)

    def test_merging_restores_the_rich_page(self):
        rich = content_page(items=rows(), layout='grid')
        self.assertEqual(merge_content(*split_content(rich)), rich)
        self.assertEqual(rich['items'][0]['playback'], 'playing')
        self.assertNotIn('image', rich['items'][3])

    def test_providers_are_told_about_invalid_hints(self):
        for hints in (dict(image='relative.png'), dict(image='ftp://example.org/a.png'), dict(image='/a\nb.png'),
                      dict(image='/' + 'a' * 2048), dict(image=3), dict(playback='paused'), dict(playback=1)):
            with self.assertRaises(Fault):
                content_item('a', 'A', **hints)
        with self.assertRaises(Fault):
            content_page(layout='carousel')
        with self.assertRaises(Fault):
            content_page(actions=[content_item('a', 'A', kind='action', action='x', playback='playing')])
        item = dict(content_item('a', 'A'), colour='red')
        with self.assertRaises(Fault):
            content_page(items=[item])

    def test_hosts_keep_the_page_when_a_presentation_is_unusable(self):
        page, _ = split_content(content_page(items=rows()))
        for presentation in (None, 'grid', {'layout': 'carousel'}, {'items': ['a']}, {'items': {'a': 'playing'}},
                             {'items': {'zzz': {'playback': 'playing'}}},
                             {'items': {'a': {'image': 'relative.png', 'playback': 'paused'}}}):
            self.assertEqual(merge_content(page, presentation), page)
        mixed = {'layout': 'list', 'future': 1, 'items': {'a': {'playback': 'started', 'image': 7, 'badge': 'new'}}}
        self.assertEqual(clean_presentation(mixed, page), {'layout': 'list', 'items': {'a': {'playback': 'started'}}})


class TransportTests(unittest.TestCase):
    def setUp(self):
        try:
            import dbus  # noqa: F401
        except ImportError:
            self.skipTest('dbus-python is unavailable')

    def test_query_results_carry_the_presentation_only_when_there_is_one(self):
        from sailplay_sdk.content import content_result
        plain = content_result(content_page('library', items=[content_item('d', 'Plain')]))
        self.assertEqual(set(plain), {'content'})
        rich = content_result(content_page('library', items=rows(), layout='grid'))
        self.assertEqual(set(rich), {'content', 'presentation'})
        self.assertEqual(str(rich['presentation']['layout']), 'grid')
        self.assertEqual(str(rich['presentation']['items']['a']['playback']), 'playing')
        self.assertEqual(set(rich['content']['items'][0]),
                         {'id', 'title', 'subtitle', 'kind', 'action', 'parameters', 'enabled'})

    def test_the_root_presentation_is_published_beside_the_root_page(self):
        from sailplay_sdk.content import _state_with_presentation
        state = _state_with_presentation({'content': content_page(items=rows(), layout='grid'), 'other': 1})
        self.assertEqual(str(state['contentPresentation']['layout']), 'grid')
        self.assertNotIn('layout', state['content'])
        state = _state_with_presentation({'content': content_page(), 'contentPresentation': {'layout': 'grid'}})
        self.assertNotIn('contentPresentation', state)


if __name__ == '__main__':
    unittest.main()
