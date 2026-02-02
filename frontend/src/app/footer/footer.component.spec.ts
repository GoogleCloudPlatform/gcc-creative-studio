/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { MatToolbarModule } from '@angular/material/toolbar';
import {ComponentFixture, TestBed} from '@angular/core/testing';
import { Router } from '@angular/router';
import { By } from '@angular/platform-browser';

import {FooterComponent} from './footer.component';

describe('FooterComponent', () => {
  let component: FooterComponent;
  let fixture: ComponentFixture<FooterComponent>;
  let mockRouter: jasmine.SpyObj<Router>;
  const PRIVACY_POLICY_URL = 'https://policies.google.com/privacy?hl=en-US';

  beforeEach(async () => {
    mockRouter = jasmine.createSpyObj('Router', ['navigateByUrl']);
    // Spy on window.open directly on the global object
    spyOn(window, 'open');

    await TestBed.configureTestingModule({
      declarations: [FooterComponent],
      imports: [MatToolbarModule],
      providers: [
        { provide: Router, useValue: mockRouter }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(FooterComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should display "Powered by Vertex AI"', () => {
    const compiled = fixture.nativeElement;
    expect(compiled.querySelector('.links-weight span').textContent).toContain('Powered by Vertex AI');
  });

  it('should display "Privacy policy" link text', () => {
    const compiled = fixture.nativeElement;
    const privacyPolicyLink = compiled.querySelectorAll('.links-weight')[1];
    expect(privacyPolicyLink.textContent).toContain('Privacy policy');
  });

  it('should display "Terms and services" link text', () => {
    const compiled = fixture.nativeElement;
    const termsOfServiceLink = compiled.querySelectorAll('.links-weight')[2];
    expect(termsOfServiceLink.textContent).toContain('Terms and services');
  });

  it('should navigate to Terms of Service page when navigateToTermsOfServicePage is called', () => {
    component.navigateToTermsOfServicePage();
    expect(mockRouter.navigateByUrl).toHaveBeenCalledWith('terms-of-service');
  });

  it('should call navigateToTermsOfServicePage when "Terms and services" link is clicked', () => {
    spyOn(component, 'navigateToTermsOfServicePage');
    const termsOfServiceLink = fixture.debugElement.queryAll(By.css('.links-weight'))[2];
    termsOfServiceLink.triggerEventHandler('click', null);
    expect(component.navigateToTermsOfServicePage).toHaveBeenCalled();
  });

  it('should open Privacy Policy URL in new tab when navigateToPrivacyPolicyPage is called', () => {
    component.navigateToPrivacyPolicyPage();
    expect(window.open).toHaveBeenCalledWith(PRIVACY_POLICY_URL, '_blank');
  });

  it('should call navigateToPrivacyPolicyPage when "Privacy policy" link is clicked', () => {
    spyOn(component, 'navigateToPrivacyPolicyPage');
    const privacyPolicyLink = fixture.debugElement.queryAll(By.css('.links-weight'))[1];
    privacyPolicyLink.triggerEventHandler('click', null);
    expect(component.navigateToPrivacyPolicyPage).toHaveBeenCalled();
  });
});
