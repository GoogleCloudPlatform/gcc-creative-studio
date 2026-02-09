import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HeaderComponent } from './header.component';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconRegistry } from '@angular/material/icon';
import { Router } from '@angular/router';
import { UserService } from '../common/services/user.service';
import { AuthService } from '../common/services/auth.service';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { of } from 'rxjs';
import { PLATFORM_ID, DebugElement } from '@angular/core';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { MatTooltipModule } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { MatMenuModule } from '@angular/material/menu';
import { NO_ERRORS_SCHEMA } from '@angular/core';

describe('HeaderComponent', () => {
  let component: HeaderComponent;
  let fixture: ComponentFixture<HeaderComponent>;
  let mockDomSanitizer: jasmine.SpyObj<DomSanitizer>;
  let mockMatIconRegistry: jasmine.SpyObj<MatIconRegistry>;
  let mockRouter: jasmine.SpyObj<Router>;
  let mockUserService: jasmine.SpyObj<UserService>;
  let mockAuthService: jasmine.SpyObj<AuthService>;
  let mockBreakpointObserver: jasmine.SpyObj<BreakpointObserver>;

  beforeEach(async () => {
    mockDomSanitizer = jasmine.createSpyObj('DomSanitizer', ['bypassSecurityTrustResourceUrl']);
    mockMatIconRegistry = jasmine.createSpyObj('MatIconRegistry', ['addSvgIcon']);
    mockRouter = jasmine.createSpyObj('Router', ['navigateByUrl', 'isActive']);
    mockUserService = jasmine.createSpyObj('UserService', ['getUserDetails']);
    mockAuthService = jasmine.createSpyObj('AuthService', ['logout', 'isUserAdmin']);
    mockBreakpointObserver = jasmine.createSpyObj('BreakpointObserver', ['observe']);

    mockMatIconRegistry.addSvgIcon.and.returnValue(mockMatIconRegistry);
    mockDomSanitizer.bypassSecurityTrustResourceUrl.and.callFake(value => value as string);
    mockBreakpointObserver.observe.and.returnValue(of({ matches: true, breakpoints: {} }));

    await TestBed.configureTestingModule({
      declarations: [HeaderComponent],
      imports: [BrowserAnimationsModule, MatTooltipModule, MatMenuModule],
      providers: [
        { provide: DomSanitizer, useValue: mockDomSanitizer },
        { provide: MatIconRegistry, useValue: mockMatIconRegistry },
        { provide: Router, useValue: mockRouter },
        { provide: UserService, useValue: mockUserService },
        { provide: AuthService, useValue: mockAuthService },
        { provide: BreakpointObserver, useValue: mockBreakpointObserver },
        { provide: PLATFORM_ID, useValue: 'browser' }
      ],
      schemas: [NO_ERRORS_SCHEMA]
    }).compileComponents();
  });

  beforeEach(() => {
    // Default user is null
    mockUserService.getUserDetails.and.returnValue(null);
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
  });

  it('should create the component', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should register SVG icons on initialization', () => {
    fixture.detectChanges();
    expect(mockMatIconRegistry.addSvgIcon).toHaveBeenCalledWith(
      'creative-studio-icon',
      '../../assets/images/creative-studio-icon.svg'
    );
  });

  it('should get user details on initialization', () => {
    const user = { name: 'Test User', email: 'test@example.com' };
    mockUserService.getUserDetails.and.returnValue(user);
    // Re-create component to run constructor with new mock value
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.currentUser).toEqual(user);
  });

  it('should handle null user details gracefully', () => {
    mockUserService.getUserDetails.and.returnValue(null);
    // Re-create component to run constructor with new mock value
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.currentUser).toBeNull();
    component.menuFixed = true;
    const tooltip = component.getTooltipText();
    expect(tooltip).toBe('Hey there ! Click to make the menu dynamic');
  });

  it('should toggle menuFixed and update localStorage', () => {
    spyOn(localStorage, 'setItem');
    component.menuFixed = false;
    component.toggleMenu();
    expect(component.menuFixed).toBe(true);
    expect(localStorage.setItem).toHaveBeenCalledWith('menuFixed', 'true');
    component.toggleMenu();
    expect(component.menuFixed).toBe(false);
    expect(localStorage.setItem).toHaveBeenCalledWith('menuFixed', 'false');
  });

  it('should return correct tooltip text when menu is fixed', () => {
    fixture.detectChanges();
    component.menuFixed = true;
    component.currentUser = { name: 'Test', email: 'test@example.com' };
    const tooltip = component.getTooltipText();
    expect(tooltip).toContain('Hey there Test! Click to make the menu dynamic');
  });

  it('should return correct tooltip text when menu is not fixed', () => {
    fixture.detectChanges();
    component.menuFixed = false;
    const tooltip = component.getTooltipText();
    expect(tooltip).toBe('Click to make the menu fixed');
  });

  it('should show tools menu on mouse enter', () => {
    component.onToolsEnter();
    expect(component.toolsMenuHovered).toBe(true);
  });

  it('should hide tools menu on mouse leave', fakeAsync(() => {
    component.onToolsLeave();
    tick(200);
    expect(component.toolsMenuHovered).toBe(false);
  }));

  it('should keep tools menu open on re-entry within timeout', fakeAsync(() => {
    component.onToolsLeave();
    tick(100);
    component.onToolsEnter();
    tick(100);
    expect(component.toolsMenuHovered).toBe(true);
  }));

  it('should navigate to home', () => {
    component.navigate();
    expect(mockRouter.navigateByUrl).toHaveBeenCalledWith('/');
  });

  it('should call authService.logout on logout', () => {
    component.logout();
    expect(mockAuthService.logout).toHaveBeenCalled();
  });

  it('should set isDesktop to true on large screens', () => {
    mockBreakpointObserver.observe.and.returnValue(of({ matches: true, breakpoints: {} }));
    // Re-create component to run constructor with new mock value
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.isDesktop).toBe(true);
  });

  it('should set isDesktop to false on small screens', () => {
    mockBreakpointObserver.observe.and.returnValue(of({ matches: false, breakpoints: {} }));
    // Re-create component to run constructor with new mock value
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    expect(component.isDesktop).toBe(false);
  });

  it('should complete the destroy subject on ngOnDestroy', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const destroy$ = (component as any).destroy$;
    spyOn(destroy$, 'next');
    spyOn(destroy$, 'complete');
    component.ngOnDestroy();
    expect(destroy$.next).toHaveBeenCalled();
    expect(destroy$.complete).toHaveBeenCalled();
  });

  it('should subscribe to breakpointObserver.observe on construction', () => {
    fixture.detectChanges();
    expect(mockBreakpointObserver.observe).toHaveBeenCalledWith([
      Breakpoints.Medium,
      Breakpoints.Large,
      Breakpoints.XLarge,
    ]);
  });

  it('should initialize menuFixed from localStorage if value is "true"', () => {
    spyOn(localStorage, 'getItem').and.returnValue('true');
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    expect(component.menuFixed).toBe(true);
  });

  it('should initialize menuFixed to false from localStorage if value is not "true"', () => {
    spyOn(localStorage, 'getItem').and.returnValue('false');
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    expect(component.menuFixed).toBe(false);
  });

  it('should initialize menuFixed to false if localStorage is not available', () => {
    spyOn(localStorage, 'getItem').and.returnValue(null);
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    expect(component.menuFixed).toBe(false);
  });

  it('should handle user with no name in tooltip', () => {
    component.menuFixed = true;
    component.currentUser = { name: '', email: 'test@example.com' };
    const tooltip = component.getTooltipText();
    expect(tooltip).toBe('Hey there ! Click to make the menu dynamic');
  });

  it('should clear timeout on onToolsEnter', () => {
    spyOn(window, 'clearTimeout');
    // Set a timeout to be cleared
    (component as any).menuTimeout = setTimeout(() => {}, 200);
    component.onToolsEnter();
    expect(window.clearTimeout).toHaveBeenCalled();
  });

  it('should show admin button for admin users and navigate on click', () => {
    mockAuthService.isUserAdmin.and.returnValue(true);
    mockRouter.isActive.and.returnValue(true); // Ensure router.isActive returns true for rendering conditions
    // Re-create component to run constructor with new mock value
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    component.menuFixed = true; // Ensure menu is visible for the test
    component.isDesktop = false; // Force !isDesktop to be true for the outer menu condition
    fixture.detectChanges();
    expect(mockAuthService.isUserAdmin).toHaveBeenCalled(); // Confirm the getter is invoked
    const adminButton: DebugElement = fixture.debugElement.query(By.css('[data-testid="admin-button"]'));
    expect(adminButton).toBeTruthy();
    adminButton.triggerEventHandler('click', null);
    expect(mockRouter.navigateByUrl).toHaveBeenCalledWith('/admin');
  });

  it('should not show admin button for non-admin users', () => {
    mockAuthService.isUserAdmin.and.returnValue(false);
    fixture.detectChanges();
    const adminButton = fixture.debugElement.query(By.css('[data-testid="admin-button"]'));
    expect(adminButton).toBeFalsy();
  });
});
