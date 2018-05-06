import numpy as np
import batoid
from .utils import bivariate_fit


def huygensPSF(optic, xs, ys, zs=None, rays=None, saveRays=False):
    """Compute a PSF via the Huygens construction.

    Parameters
    ----------
    optic : batoid.Optic
        Optical system
    xs, ys : ndarray
        Coordinates at which to evaluate the PSF in the optic.outCoordSys system.
    zs : ndarray, optional
        Optional z coordinates at which to evaluate the PSF.  Default: 0.
    rays : RayVector
        Input rays to optical system.
    saveRays : bool, optional
        Whether or not to preserve input rays or overwrite.  Default: False

    Returns
    -------
    psf : ndarray
        The PSF

    Notes
    -----
    The Huygens construction is to evaluate the PSF as

    I(r) \propto \Sum_u exp(i phi(u)) exp(i k(u).r)

    The u are assumed to uniformly sample the entrance pupil.  The phis are the phases of the exit
    rays evaluated at a single arbitrary time.  The k(u) indicates the conversion of the uniform
    entrance pupil samples into nearly (though not exactly) uniform samples in k-space of the output
    rays.
    """
    if zs is None:
        zs = np.zeros_like(xs)
    if saveRays:
        rays = batoid.RayVector(rays)  # Make a copy
    rays, outCoordSys = optic.traceInPlace(rays)
    batoid._batoid.trimVignettedInPlace(rays)
    # transform = batoid.CoordTransform(outCoordSys, batoid.CoordSys())
    # transform.applyForwardInPlace(rays)
    points = np.concatenate([aux[..., None] for aux in (xs, ys, zs)], axis=-1)
    time = rays[0].t0
    amplitudes = np.empty(xs.shape, dtype=np.complex128)
    for (i, j) in np.ndindex(xs.shape):
        amplitudes[i, j] = batoid._batoid.sumAmplitudeMany(
            rays,
            points[i, j],
            time
        )
    return np.abs(amplitudes)**2


def drdth(optic, wavelength, theta_x, theta_y, nx=16):
    """Calculate derivative of focal plane coord with respect to field angle.

    Parameters
    ----------
    optic : batoid.Optic
        Optical system
    theta_x, theta_y : float
        Field angle in radians
    wavelength : float
        Wavelength in meters
    nx : int, optional
        Size of ray grid to use.

    Returns
    -------
    drdth : (2, 2), ndarray
        Jacobian transformation matrix for converting between (theta_x, theta_y)
        and (x, y) on the focal plane.

    Notes
    -----
        This is essentially the inverse plate scale in meters per radian.
    """
    # We just use a finite difference approach here.
    dth = 1e-5

    nominalCos = [np.sin(theta_x),
                  np.sin(theta_y),
                  -np.sqrt(1.0 - np.sin(theta_x)**2 - np.sin(theta_y)**2)]
    dthxCos = [np.sin(theta_x+dth),
               np.sin(theta_y),
               -np.sqrt(1.0 - np.sin(theta_x+dth)**2 - np.sin(theta_y)**2)]
    dthyCos = [np.sin(theta_x),
               np.sin(theta_y+dth),
               -np.sqrt(1.0 - np.sin(theta_x)**2 - np.sin(theta_y+dth)**2)]

    rays = batoid.rayGrid(optic.dist, optic.pupilSize,
        nominalCos[0], nominalCos[1], nominalCos[2],
        nx, wavelength=wavelength, medium=optic.inMedium)

    rays_x = batoid.rayGrid(optic.dist, optic.pupilSize,
        dthxCos[0], dthxCos[1], dthxCos[2],
        nx, wavelength=wavelength, medium=optic.inMedium)

    rays_y = batoid.rayGrid(optic.dist, optic.pupilSize,
        dthyCos[0], dthyCos[1], dthyCos[2],
        nx, wavelength=wavelength, medium=optic.inMedium)

    optic.traceInPlace(rays)
    optic.traceInPlace(rays_x)
    optic.traceInPlace(rays_y)

    batoid.trimVignettedInPlace(rays)
    batoid.trimVignettedInPlace(rays_x)
    batoid.trimVignettedInPlace(rays_y)

    # meters / radian
    drx_dthx = (np.mean(rays_x.x) - np.mean(rays.x))/dth
    drx_dthy = (np.mean(rays_y.x) - np.mean(rays.x))/dth
    dry_dthx = (np.mean(rays_x.y) - np.mean(rays.y))/dth
    dry_dthy = (np.mean(rays_y.y) - np.mean(rays.y))/dth

    return np.array([[drx_dthx, dry_dthx], [drx_dthy, dry_dthy]])


def dthdr(optic, wavelength, theta_x, theta_y, nx=16):
    """Calculate derivative of field angle with respect to focal plane coordinate.

    Parameters
    ----------
    optic : batoid.Optic
        Optical system
    theta_x, theta_y : float
        Field angle in radians
    wavelength : float
        Wavelength in meters
    nx : int, optional
        Size of ray grid to use.

    Returns
    -------
    dthdr : (2, 2), ndarray
        Jacobian transformation matrix for converting between (x, y) on the focal plane and
        field angle (theta_x, theta_y).

    Notes
    -----
        This is essentially the plate scale in radians per meter.
    """
    return np.linalg.inv(drdth(optic, wavelength, theta_x, theta_y, nx=nx))


def dkdu(optic, wavelength, theta_x, theta_y, nx=16):
    """Calculate derivative of outgoing ray k-vector with respect to incoming ray
    pupil coordinate.


    Parameters
    ----------
    optic : batoid.Optic
        Optical system
    theta_x, theta_y : float
        Field angle in radians
    wavelength : float
        Wavelength in meters
    nx : int, optional
        Size of ray grid to use.

    Returns
    -------
    dkdu : (2, 2), ndarray
        Jacobian transformation matrix for converting between (kx, ky) of rays impacting the focal
        plane and initial field angle.

    Notes
    -----
        This is essentially the plate scale in radians per meter.
    """
    rays = batoid.rayGrid(
        optic.dist, optic.pupilSize,
        theta_x, theta_y, -1.0,
        nx, wavelength, optic.inMedium
    )

    pupilRays = batoid._batoid.propagatedToTimesMany(rays, np.zeros_like(rays.x))
    ux = np.array(pupilRays.x)
    uy = np.array(pupilRays.y)

    optic.traceInPlace(rays)
    w = np.where(1-rays.isVignetted)[0]
    ux = ux[w]
    uy = uy[w]

    kx = rays.kx[w]
    ky = rays.ky[w]

    soln = bivariate_fit(ux, uy, kx, ky)
    return soln[1:]


def wavefront(optic, wavelength, theta_x=0, theta_y=0, nx=32, rays=None, saveRays=False,
              sphereRadius=None):
    if rays is None:
        xcos = np.sin(theta_x)
        ycos = np.sin(theta_y)
        zcos = -np.sqrt(1.0 - xcos**2 - ycos**2)

        rays = batoid.rayGrid(
                optic.dist, optic.pupilSize, xcos, ycos, zcos, nx, wavelength, optic.inMedium)
    if saveRays:
        rays = batoid.RayVector(rays)
    if sphereRadius is None:
        sphereRadius = optic.sphereRadius

    outCoordSys = batoid.CoordSys()
    optic.traceInPlace(rays, outCoordSys=outCoordSys)
    goodRays = batoid._batoid.trimVignetted(rays)
    point = np.array([np.mean(goodRays.x), np.mean(goodRays.y), np.mean(goodRays.z)])

    # We want to place the vertex of the reference sphere one radius length away from the
    # intersection point.  So transform our rays into that coordinate system.
    transform = batoid.CoordTransform(
            outCoordSys, batoid.CoordSys(point+np.array([0,0,sphereRadius])))
    transform.applyForwardInPlace(rays)

    sphere = batoid.Sphere(-sphereRadius)
    sphere.intersectInPlace(rays)
    goodRays = batoid._batoid.trimVignetted(rays)
    # Should potentially try to make the reference time w.r.t. the chief ray instead of the mean
    # of the good (unvignetted) rays.
    t0 = np.mean(goodRays.t0)

    ts = rays.t0[:]
    isV = rays.isVignetted[:]
    ts -= t0
    ts /= wavelength
    wf = np.ma.masked_array(ts, mask=isV)
    return wf


def fftPSF(optic, wavelength, theta_x, theta_y, nx=32, pad_factor=2):
    L = optic.pupilSize*pad_factor
    im_dtheta = wavelength / L
    wf = wavefront(optic, wavelength, theta_x, theta_y, nx).reshape(nx, nx)
    pad_size = nx*pad_factor
    expwf = np.zeros((pad_size, pad_size), dtype=np.complex128)
    start = pad_size//2-nx//2
    stop = pad_size//2+nx//2
    expwf[start:stop, start:stop][~wf.mask] = np.exp(2j*np.pi*wf[~wf.mask])
    psf = np.abs(np.fft.fftshift(np.fft.fft2(np.fft.fftshift(expwf))))**2
    return im_dtheta, psf


def zernike(optic, wavelength, theta_x, theta_y, jmax=22, nx=32, eps=0.0):
    import galsim.zernike as zern

    xcos = np.sin(theta_x)
    ycos = np.sin(theta_y)
    zcos = -np.sqrt(1.0 - xcos**2 - ycos**2)

    rays = batoid.rayGrid(
            optic.dist, optic.pupilSize, xcos, ycos, zcos, nx, wavelength, optic.inMedium)

    orig_x = np.array(rays.x)
    orig_y = np.array(rays.y)

    wf = wavefront(optic, wavelength, rays=rays)

    w = ~wf.mask

    basis = zern.zernikeBasis(
            jmax, orig_x[w], orig_y[w],
            R_outer=optic.pupilSize/2, R_inner=optic.pupilSize/2*eps
    )
    coefs, _, _, _ = np.linalg.lstsq(basis.T, wf[w])

    return coefs


def newFFTPSF(optic, wavelength, theta_x, theta_y, nx=64, pupilFactor=2):
    xcos = np.sin(theta_x)
    ycos = np.sin(theta_y)
    zcos = -np.sqrt(1.0 - xcos**2 - ycos**2)

    # We could incorporate pupilFactor here, but since we know that all the
    # additional rays should vignette, we'll delay until later.
    rays = batoid.rayGrid(
        optic.dist, optic.pupilSize,
        xcos, ycos, zcos,
        nx, wavelength, optic.inMedium
    )

    wf = wavefront(optic, wavelength, rays=rays).reshape(nx, nx)

    padSize = nx*pupilFactor
    expwf = np.zeros((padSize, padSize), dtype=np.complex128)
    start = padSize//2 - nx//2
    stop = padSize//2 + nx//2
    expwf[start:stop, start:stop][~wf.mask] = np.exp(2j*np.pi*wf[~wf.mask])
    arr = np.abs(np.fft.fftshift(np.fft.fft2(np.fft.fftshift(expwf))))**2

    # Now the tricky part, what is the coordinate system for the output array?
    du = optic.pupilSize/nx
    N = nx * pupilFactor
    u1 = np.array([1,0])*du
    u2 = np.array([0,1])*du

    # Convert pupil coords to Fourier focal plane coords
    _dkdu = dkdu(optic, wavelength, theta_x, theta_y, nx=nx)
    q1 = _dkdu[0,0]*u1 + _dkdu[0,1]*u2
    q2 = _dkdu[1,0]*u1 + _dkdu[1,1]*u2

    # Use reciprical lattice vectors for focal plane coords...
    norm = 2*np.pi/(q1[0]*q2[1] - q1[1]*q2[0])/N
    x1 = norm*np.array([q2[1], -q2[0]])
    x2 = norm*np.array([q1[1], -q1[0]])

    # Also finally convert to sky coords
    dthdx = dthdr(optic, wavelength, theta_x, theta_y, nx=nx)
    th1 = dthdx[0,0]*x1 + dthdx[0,1]*x2
    th2 = dthdx[1,0]*x1 + dthdx[1,1]*x2

    # th1 and th2 now indicate the field angles corresponding to rows and columns.
    return th1, th2, arr
