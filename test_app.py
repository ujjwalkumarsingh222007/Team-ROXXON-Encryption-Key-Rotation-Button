import unittest
import json
import os
from app import app, load_data, save_data
from kms import KMSManager, _parse_aws_exception, _get_error_solution, DEFAULT_KMS_KEY_ID

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
        # Verify default key is the real KMS key ID
        self.assertEqual(data['current_key']['key_id'], '4f206dc3-dea4-4fcf-baee-8624627af374')

    def test_kms_status_endpoint(self):
        response = self.client.get('/api/kms/status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('configured', data)
        self.assertIn('status', data)
        self.assertIn('mode', data)
        # Ensure private key material or credentials are NEVER exposed
        self.assertNotIn('key_material', data)
        self.assertNotIn('secret_access_key', data)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', data)

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
        self.assertEqual(data['key_id'], '4f206dc3-dea4-4fcf-baee-8624627af374')
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

    def test_kms_error_parsing_and_safety(self):
        # Test error code parsing
        class MockBotoClientError(Exception):
            def __init__(self, code, message):
                self.response = {"Error": {"Code": code, "Message": message}}

        # 1. Expired token
        msg, code = _parse_aws_exception(MockBotoClientError("ExpiredToken", "The security token included in the request is expired"), DEFAULT_KMS_KEY_ID, "us-east-1")
        self.assertEqual(code, "EXPIRED_TOKEN")
        self.assertIn("expired", msg.lower())

        # 2. Access Denied
        msg, code = _parse_aws_exception(MockBotoClientError("AccessDeniedException", "User is not authorized"), DEFAULT_KMS_KEY_ID, "us-east-1")
        self.assertEqual(code, "ACCESS_DENIED")
        self.assertIn("Access Denied", msg)

        # 3. Not Found
        msg, code = _parse_aws_exception(MockBotoClientError("NotFoundException", "Key not found"), DEFAULT_KMS_KEY_ID, "us-east-1")
        self.assertEqual(code, "KEY_NOT_FOUND")

        # 4. Solutions are provided
        sol = _get_error_solution("EXPIRED_TOKEN", DEFAULT_KMS_KEY_ID, "us-east-1")
        self.assertIn("expired", sol.lower())

    def test_diagnostic_endpoint(self):
        response = self.client.get('/api/diagnostic')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('env_file_found', data)
        self.assertIn('app_mode', data)
        self.assertIn('aws_access_key_id_present', data)
        self.assertIn('aws_secret_access_key_present', data)
        self.assertIn('aws_session_token_present', data)
        self.assertIn('aws_region', data)
        self.assertIn('kms_key_id', data)
        self.assertIn('boto3_available', data)
        self.assertIn('kms_configured', data)
        # Verify no actual secrets or keys are returned
        for key, val in data.items():
            if 'key' in key.lower() and key != 'kms_key_id':
                self.assertIsInstance(val, bool)

    def test_real_kms_mode_unconfigured_error(self):
        # When KMS credentials are not configured, real mode must return 400 with clear message
        # without crashing and without fallback to demo mode
        kms_mgr = KMSManager()
        if not kms_mgr.is_configured():
            response = self.client.post('/api/rotate', json={"mode": "real", "scenario": "none"})
            self.assertEqual(response.status_code, 400)
            data = json.loads(response.data)
            self.assertFalse(data['success'])
            self.assertEqual(data['status'], 'FAILED')
            self.assertEqual(data['kms_mode'], 'real')
            self.assertIn('solution', data)

if __name__ == '__main__':
    unittest.main()
