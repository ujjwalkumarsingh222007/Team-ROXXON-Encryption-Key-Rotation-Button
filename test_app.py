import unittest
import json
import os
from app import app, load_data, save_data

class AppTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_health_endpoint(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['backend'], 'online')
        self.assertIn('mode', data)
        self.assertIn('aws', data)

    def test_status_endpoint(self):
        response = self.client.get('/api/status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'online')
        self.assertIn('aws_services', data)
        self.assertIn('current_key', data)
        self.assertIn('device', data)

    def test_kms_status_endpoint(self):
        response = self.client.get('/api/kms/status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('configured', data)
        self.assertIn('status', data)
        self.assertIn('mode', data)
        # Ensure private key material is NEVER exposed
        self.assertNotIn('key_material', data)
        self.assertNotIn('secret_access_key', data)

    def test_device_status_endpoint(self):
        response = self.client.get('/api/device-status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('device', data)
        self.assertEqual(data['device']['device_id'], 'ESP32-001')

    def test_history_endpoint(self):
        response = self.client.get('/api/history')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('history', data)
        self.assertIsInstance(data['history'], list)

    def test_rotation_demo_mode(self):
        response = self.client.post('/api/rotate', json={"mode": "demo", "scenario": "none"})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'SUCCESS')
        self.assertIn('key_id', data)
        self.assertIn('version', data)
        self.assertEqual(data['kms_mode'], 'SIMULATED')
        self.assertTrue(len(data['steps']) > 0)

    def test_rotate_key_alias(self):
        response = self.client.post('/api/rotate-key', json={"mode": "demo", "scenario": "none"})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])

    def test_demo_failure_scenarios(self):
        # 1. IoT Timeout
        res_iot = self.client.post('/api/rotate', json={"mode": "demo", "scenario": "iot_timeout"})
        self.assertEqual(res_iot.status_code, 400)
        data_iot = json.loads(res_iot.data)
        self.assertFalse(data_iot['success'])
        self.assertIn("Timeout", data_iot['error'])

        # 2. Lambda Error
        res_lam = self.client.post('/api/rotate', json={"mode": "demo", "scenario": "lambda_error"})
        self.assertEqual(res_lam.status_code, 400)
        data_lam = json.loads(res_lam.data)
        self.assertFalse(data_lam['success'])
        self.assertIn("Lambda", data_lam['error'])

        # 3. KMS Error
        res_kms = self.client.post('/api/rotate', json={"mode": "demo", "scenario": "kms_error"})
        self.assertEqual(res_kms.status_code, 400)
        data_kms = json.loads(res_kms.data)
        self.assertFalse(data_kms['success'])
        self.assertTrue("Permission" in data_kms['error'] or "KMS" in data_kms['error'])

        # 4. OLED Error
        res_oled = self.client.post('/api/rotate', json={"mode": "demo", "scenario": "oled_error"})
        self.assertEqual(res_oled.status_code, 400)
        data_oled = json.loads(res_oled.data)
        self.assertFalse(data_oled['success'])
        self.assertIn("OLED", data_oled['error'])

    def test_key_id_preservation(self):
        # Verify that KMS Key ID is preserved across rotations while version increases
        data_before = load_data()
        orig_key_id = data_before["current_key"]["key_id"]
        orig_version = data_before["current_key"]["version"]

        # Run rotation
        self.client.post('/api/rotate', json={"mode": "demo", "scenario": "none"})

        data_after = load_data()
        self.assertEqual(data_after["current_key"]["key_id"], orig_key_id)
        self.assertEqual(data_after["current_key"]["version"], orig_version + 1)

if __name__ == '__main__':
    unittest.main()
