// Explicit real-hardware smoke test. Requires the API, web UI and paired watcher.
import { chromium, expect } from '@playwright/test';

const baseURL = 'http://127.0.0.1:5173';
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(baseURL);
  await expect(page.getByText('REAL DEVICE · LOCAL COLLECTOR')).toBeVisible({ timeout: 15000 });
  const selector = page.getByRole('combobox', { name: 'Selected device' });
  const deviceId = await selector.inputValue();
  const devices = await (await page.request.get(baseURL + '/api/devices')).json();
  const device = devices.find(d => d.id === deviceId);
  expect(device.demo).toBe(false);
  expect(device.manufacturer).toBe('Apple');
  expect(device.os).toMatch(/^macOS /);
  await page.getByRole('button', { name: 'Run diagnostic scan', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('paired macOS agent');
  await page.getByRole('button', { name: 'Request collector scan' }).click();
  await expect(page.getByText('Collector scan · completed')).toBeVisible({ timeout: 120000 });
  const readings = await (await page.request.get(`${baseURL}/api/devices/${deviceId}/evidence`)).json();
  expect(readings.length).toBeGreaterThan(0);
  expect(readings.every(r => !r.source.includes('Fictional'))).toBe(true);
  expect(readings.find(r => r.key === 'cpu_temperature').status).toBe('unsupported');
  if (device.model.includes('Mac mini')) {
    expect(readings.find(r => r.key === 'battery_presence').status).toBe('unsupported');
    expect(readings.some(r => r.key === 'cycle_count')).toBe(false);
  }
  await page.getByRole('button', { name: 'Inspect CPU / cooling', exact: true }).click();
  await expect(page.locator('.inspector h2')).toHaveText('CPU / cooling');
  await page.screenshot({ path: 'data/local/macos-workbench.png', fullPage: true });
  await selector.selectOption('demo-thinkpad');
  await expect(page.getByText('DEMO DATA · FICTIONAL DEVICE')).toBeVisible();
  // Polling must not override an explicit user selection.
  await page.waitForTimeout(5500);
  await expect(selector).toHaveValue('demo-thinkpad');
  await page.reload();
  await expect(selector).toHaveValue(deviceId);
  await expect(page.getByText('REAL DEVICE · LOCAL COLLECTOR')).toBeVisible();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('dialog').getByText('Agent connection · macOS / Windows')).toBeVisible();
  await expect(page.locator('.setup-command')).toContainText('--watch');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  expect(errors).toEqual([]);
  console.log(`Real macOS browser scan passed: ${device.model}, ${device.os}, ${readings.length} readings; demo isolation and default selection verified.`);
} finally {
  await browser.close();
}
