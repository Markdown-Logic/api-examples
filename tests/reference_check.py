#!/usr/bin/env python3
"""Offline integrity and route coverage for the unchanged public spec snapshot."""
import hashlib,json,pathlib,re,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Reference(unittest.TestCase):
    def test_snapshot_integrity(self):
        raw=(ROOT/'reference/openapi.json').read_bytes(); meta=json.loads((ROOT/'reference/provenance.json').read_text()); spec=json.loads(raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),meta['sha256']); self.assertEqual(len(raw),meta['bytes'])
        self.assertEqual(spec['info']['version'],meta['infoVersion']); self.assertEqual(spec['servers'],[{'url':'https://api.markdownlogic.com'}])
    def test_matching_routes_are_published(self):
        spec=json.loads((ROOT/'reference/openapi.json').read_text())
        for path,methods in {
            '/api/v1/teams/{teamId}/projects':['get','post'], '/api/v1/projects/{projectId}':['patch'],
            '/api/v1/projects/{projectId}/artifacts':['post'], '/api/v1/projects/{projectId}/documents/{documentId}':['get','put'],
            '/api/v1/projects/{projectId}/documents/{documentId}/versions':['get'],
            '/api/v1/projects/{projectId}/documents/{documentId}/versions/{versionId}':['get'],
            '/api/v1/projects/{projectId}/documents/{documentId}/renders/{format}':['get'],
            '/api/v1/projects/{projectId}/documents/{documentId}/shares':['post'],
            '/api/v1/webhooks/events':['get'], '/api/v1/teams/{teamId}/webhooks':['post'],
        }.items():
            for method in methods: self.assertIn(method,spec['paths'][path],path)
    def test_relative_document_links(self):
        for path in ROOT.rglob('*.md'):
            if any(part in {'.git','target','bin','obj'} for part in path.parts): continue
            for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
                if '://' in link or link.startswith('#'): continue
                target=link.split('#')[0]
                self.assertTrue((path.parent/target).exists(),str(path.relative_to(ROOT))+' -> '+link)
if __name__=='__main__': unittest.main(verbosity=2)
