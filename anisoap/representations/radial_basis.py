import warnings

import numpy as np
from metatensor import TensorMap
from scipy.special import gamma, hyp1f1


def inverse_matrix_sqrt(matrix: np.array, rcond=1e-8, tol=1e-3):
    """
    Returns the inverse matrix square root.
    The inverse square root of the overlap matrix (or slices of the overlap matrix) yields the
    orthonormalization matrix
    Args:
        matrix: np.array
            Symmetric square matrix to find the inverse square root of

        rcond: float
            Lower bound for eigenvalues for inverse square root

        tol: float
            Tolerance for differences between original matrix and reconstruction via
            inverse square root

    Returns:
        inverse_sqrt_matrix: S^{-1/2}

    """
    if not np.allclose(matrix, matrix.conjugate().T):
        raise ValueError("Matrix is not hermitian")
    eva, eve = np.linalg.eigh(matrix)
    eve = eve[:, eva > rcond]
    eva = eva[eva > rcond]

    result = eve @ np.diag(1 / np.sqrt(eva)) @ eve.T

    # Do quick test to make sure inverse square of the inverse matrix sqrt succeeded
    # This should succed for most cases (e.g. GTO orders up to 100), if not the matrix likely wasn't a gram matrix to start with.
    matrix2 = np.linalg.pinv(result @ result)
    if np.linalg.norm(matrix - matrix2) > tol:
        raise ValueError(
            f"Incurred Numerical Imprecision {np.linalg.norm(matrix-matrix2)= :.8f}"
        )
    return result


def gto_square_norm(n, sigma):
    """
    Compute the square norm of GTOs (inner product of itself over R^3).
    An unnormalized GTO of order n is \phi_n = r^n * e^{-r^2/(2*\sigma^2)}
    The square norm of the unnormalized GTO has an analytic solution:
    <\phi_n | \phi_n> = \int_0^\infty dr r^2 |\phi_n|^2 = 1/2 * \sigma^{2n+3} * \Gamma(n+3/2)
    Args:
        n: order of the GTO
        sigma: width of the GTO

    Returns:
        square norm: The square norm of the unnormalized GTO
    """
    return 0.5 * sigma ** (2 * n + 3) * gamma(n + 1.5)


def gto_prefactor(n, sigma):
    """
    Computes the normalization prefactor of an unnormalized GTO.
    This prefactor is simply 1/sqrt(square_norm_area).
    Scaling a GTO by this prefactor will ensure that the GTO has square norm equal to 1.
    Args:
        n: order of GTO
        sigma: width of GTO

    Returns:
        N: normalization constant

    """
    return np.sqrt(1 / gto_square_norm(n, sigma))


def shifted_gto_square_norm(n, sigma, s):
    """ """
    kummer_1 = hyp1f1(-n - 1, 1 / 2, -(s**2.0) / (2 * sigma**2.0))
    kummer_2 = hyp1f1(-n - 1 / 2, 3 / 2, -(s**2.0) / (2 * sigma**2.0))

    return (
        2.0**n
        * (sigma**2.0) ** (n + 1)
        * (
            np.sqrt(2) * np.abs(sigma) * gamma(n + 3.0 / 2) * kummer_1
            + 2 * s * gamma(n + 2) * kummer_2
        )
    )


def shifted_gto_prefactor(n, sigma, s):
    """ """
    return np.sqrt(1 / shifted_gto_square_norm(n, sigma, s))


def shifted_gto_overlap(n, m, sigma_n, sigma_m, s_n, s_m):
    """ """
    N_n = shifted_gto_prefactor(n, sigma_n, s_n)
    N_m = shifted_gto_prefactor(m, sigma_m, s_m)
    n_eff = (n + m) / 2
    sigma_eff = np.sqrt(sigma_n**2 * sigma_m**2 / (sigma_n**2 + sigma_m**2))
    s_eff = (sigma_m**2.0 * s_n + sigma_n**2.0 * s_m) / (
        sigma_n**2 + sigma_m**2
    )
    return N_n * N_m * shifted_gto_square_norm(n_eff, sigma_eff, s_eff)


def monomial_square_norm(n, r_cut):
    """
    Compute the square norm of monomials (inner product of itself over R^3).

    Args:
        n: order of the basis

    Returns:
        square norm: The square norm of the unnormalized basis
    """
    return r_cut ** (2 * n + 3) / (2 * n + 3)


def monomial_prefactor(n, r_cut):
    """
    Computes the normalization prefactor of an unnormalized monomial basis.
    This prefactor is simply 1/sqrt(square_norm_area).
    Scaling a basis by this prefactor will ensure that the basis has square norm equal to 1.
    Args:
        n: order of basis

    Returns:
        N: normalization constant

    """
    return np.sqrt(1 / monomial_square_norm(n, r_cut))


def monomial_overlap(n, m, r_cut):
    """

    ---Returns---
    S: overlap of the two normalized GTOs
    """
    N_n = monomial_prefactor(n, r_cut)
    N_m = monomial_prefactor(m, r_cut)
    n_eff = (n + m) / 2
    return N_n * N_m * monomial_square_norm(n_eff, r_cut)


class _RadialBasis:
    """
    Class for precomputing and storing all results related to the radial basis.
    This helps to keep a cleaner main code by avoiding if-else clauses
    related to the radial basis.

    Code relating to GTO orthonormalization is heavily inspired by work done in librascal, specifically this
    codebase here: https://github.com/lab-cosmo/librascal/blob/8405cbdc0b5c72a5f0b0c93593100dde348bb95f/bindings/rascal/utils/radial_basis.py

    """

    def __init__(
        self,
        radial_basis,
        max_angular,
        cutoff_radius,
        max_radial=None,
        rcond=1e-8,
        tol=1e-3,
    ):
        # Store all inputs into internal variables
        self.radial_basis = radial_basis
        self.max_angular = max_angular
        self.cutoff_radius = cutoff_radius
        self.rcond = rcond
        self.tol = tol

        # As part of the initialization, compute the number of radial basis
        # functions, num_n, for each angular frequency l.
        # If nmax is given, num_n = nmax + 1 (n ranges from 0 to nmax)
        self.num_radial_functions = []
        for l in range(max_angular + 1):
            if max_radial is None:
                num_n = (max_angular - l) // 2 + 1
                self.num_radial_functions.append(num_n)
            elif isinstance(max_radial, list):
                if len(max_radial) <= l:
                    raise ValueError(
                        "If you specify a list of number of radial components, this list must be of length {}. Received {}.".format(
                            max_angular + 1, len(max_radial)
                        )
                    )
                if not isinstance(max_radial[l], int):
                    raise ValueError("`max_radial` must be None, int, or list of int")
                self.num_radial_functions.append(max_radial[l] + 1)
            elif isinstance(max_radial, int):
                self.num_radial_functions.append(max_radial + 1)
            else:
                raise ValueError("`max_radial` must be None, int, or list of int")

    # Get number of radial functions
    def get_num_radial_functions(self):
        return self.num_radial_functions

    def plot_basis(self, n_r=100):
        """ """
        from matplotlib import pyplot as plt

        rs = np.linspace(0, self.cutoff_radius, n_r)
        plt.plot(rs, self.get_basis(rs))


class MonomialBasis(_RadialBasis):
    def __init__(
        self,
        max_angular,
        cutoff_radius,
        max_radial=None,
        rcond=1e-8,
        tol=1e-3,
    ):
        super().__init__("monomial", max_angular, cutoff_radius, max_radial, rcond, tol)

        # As part of the initialization, compute the orthonormalization matrix for GTOs
        # If we are using the monomial basis, set self.overlap_matrix equal to None
        self.overlap_matrix = None
        self.overlap_matrix = self.calc_overlap_matrix()

    # For each particle pair (i,j), we are provided with the three quantities
    # that completely define the Gaussian distribution, namely
    # the pair distance r_ij, the rotation matrix specifying the orientation
    # of particle j's ellipsoid, as well the the three lengths of the
    # principal axes.
    # Combined with the choice of radial basis, these completely specify
    # the mathematical problem, namely the integral that needs to be
    # computed, which will be of the form
    # integral gaussian(x,y,z) * polynomial(x,y,z) dx dy dz
    # This function deals with the Gaussian part, which is specified
    # by a precision matrix (inverse of covariance) and its center.
    # The current function computes the covariance matrix and the center
    # for the provided parameters as well as choice of radial basis.
    def compute_gaussian_parameters(self, r_ij, lengths, rotation_matrix):
        # Initialization
        center = r_ij
        diag = np.diag(1 / lengths**2)
        precision = rotation_matrix @ diag @ rotation_matrix.T

        return precision, center

    def calc_overlap_matrix(self):
        """
        Computes the overlap matrix for Monomnials over a fixed interval.
        The overlap matrix is a Gram matrix whose entries are the overlap: S_{ij} = \int_0^r_cut dr r^2 phi_i phi_j
        The overlap has an analytic solution (see above functions).
        The overlap matrix is the first step to generating an orthonormal basis set of functions (Lodwin Symmetric
        Orthonormalization). The actual orthonormalization matrix cannot be fully precomputed because each tensor
        block use a different set of bases. Hence, we precompute the full overlap matrix of dim l_max, and while
        orthonormalizing each tensor block, we generate the respective orthonormal matrices from slices of the full
        overlap matrix.

        Returns:
            S: 2D array. The overlap matrix
        """
        max_deg = np.max(
            np.arange(self.max_angular + 1) + 2 * np.array(self.num_radial_functions)
        )
        n_grid = np.arange(max_deg)
        S = monomial_overlap(
            n_grid[:, np.newaxis], n_grid[np.newaxis, :], self.cutoff_radius
        )
        return S

    def orthonormalize_basis(self, features: TensorMap):
        """
        Apply an in-place orthonormalization on the features, using Lodwin Symmetric Orthonormalization.
        Each block in the features TensorMap uses a basis set of l + 2n, so we must take the appropriate slices of
        the overlap matrix to compute the orthonormalization matrix.
        An instructive example of Lodwin Symmetric Orthonormalization of a 2-element basis set is found here:
        https://booksite.elsevier.com/9780444594365/downloads/16755_10030.pdf

        Parameters:
            features: A TensorMap whose blocks' values we wish to orthonormalize. Note that features is modified in place, so a
            copy of features must be made before the function if you wish to retain the unnormalized values.
            radial_basis: An instance of _RadialBasis

        Returns:
            normalized_features: features containing values multiplied by proper normalization factors.
        """
        # In-place modification.

        for label, block in features.items():
            # Each block's `properties` dimension contains radial channels for each neighbor species
            # Hence we have to iterate through each neighbor species and orthonormalize the block in subblocks
            # Each subblock is indexed using the neighbor_mask boolean array.
            neighbors = np.unique(block.properties["neighbor_species"])
            for neighbor in neighbors:
                l = label["angular_channel"]
                neighbor_mask = block.properties["neighbor_species"] == neighbor
                n_arr = block.properties["n"][neighbor_mask].flatten()
                l_2n_arr = l + 2 * n_arr
                # normalize all the GTOs by the appropriate prefactor first, since the overlap matrix is in terms of
                # normalized GTOs
                prefactor_arr = monomial_prefactor(l_2n_arr, self.cutoff_radius)
                block.values[:, :, neighbor_mask] *= prefactor_arr

                overlap_matrix_slice = self.overlap_matrix[l_2n_arr, :][:, l_2n_arr]
                orthonormalization_matrix = inverse_matrix_sqrt(
                    overlap_matrix_slice, self.rcond, self.tol
                )
                block.values[:, :, neighbor_mask] = np.einsum(
                    "ijk,kl->ijl",
                    block.values[:, :, neighbor_mask],
                    orthonormalization_matrix,
                )

        return features

    def get_basis(self, rs):
        all_gs = np.empty(shape=(len(rs), 1))
        for l in range(0, self.max_angular):
            n_arr = np.arange(self.num_radial_functions[l])
            l_2n_arr = l + 2 * n_arr

            gs = np.array([(rs ** (2 * n + l)) for n in n_arr]).T

            prefactor_arr = monomial_prefactor(l_2n_arr, self.cutoff_radius)

            gs *= prefactor_arr

            overlap_matrix_slice = self.overlap_matrix[l_2n_arr, :][:, l_2n_arr]
            orthonormalization_matrix = inverse_matrix_sqrt(
                overlap_matrix_slice, self.rcond, self.tol
            )
            gs = np.einsum(
                "jk,kl->jl",
                gs,
                orthonormalization_matrix,
            )
            if all_gs is None:
                all_gs = gs.copy()

            all_gs = np.hstack((all_gs, gs))
        return all_gs[:, 1:]


class GTORadialBasis(_RadialBasis):
    def __init__(
        self,
        max_angular,
        cutoff_radius,
        *,
        radial_gaussian_width,
        max_radial=None,
        rcond=1e-8,
        tol=1e-3,
    ):
        super().__init__("gto", max_angular, cutoff_radius, max_radial, rcond, tol)
        self.radial_gaussian_width = radial_gaussian_width

        # As part of the initialization, compute the orthonormalization matrix for GTOs
        # If we are using the monomial basis, set self.overlap_matrix equal to None
        self.overlap_matrix = self.calc_overlap_matrix()

    # For each particle pair (i,j), we are provided with the three quantities
    # that completely define the Gaussian distribution, namely
    # the pair distance r_ij, the rotation matrix specifying the orientation
    # of particle j's ellipsoid, as well the the three lengths of the
    # principal axes.
    # Combined with the choice of radial basis, these completely specify
    # the mathematical problem, namely the integral that needs to be
    # computed, which will be of the form
    # integral gaussian(x,y,z) * polynomial(x,y,z) dx dy dz
    # This function deals with the Gaussian part, which is specified
    # by a precision matrix (inverse of covariance) and its center.
    # The current function computes the covariance matrix and the center
    # for the provided parameters as well as choice of radial basis.
    def compute_gaussian_parameters(self, r_ij, lengths, rotation_matrix):
        # Initialization
        center = r_ij
        diag = np.diag(1 / lengths**2)
        precision = rotation_matrix @ diag @ rotation_matrix.T

        # GTO basis with uniform Gaussian width in the basis functions
        sigma = self.radial_gaussian_width
        precision += np.eye(3) / sigma**2
        center -= 1 / sigma**2 * np.linalg.solve(precision, r_ij)

        return precision, center

    def calc_overlap_matrix(self):
        """
        Computes the overlap matrix for GTOs.
        The overlap matrix is a Gram matrix whose entries are the overlap: S_{ij} = \int_0^\infty dr r^2 phi_i phi_j
        The overlap has an analytic solution (see above functions).
        The overlap matrix is the first step to generating an orthonormal basis set of functions (Lodwin Symmetric
        Orthonormalization). The actual orthonormalization matrix cannot be fully precomputed because each tensor
        block use a different set of GTOs. Hence, we precompute the full overlap matrix of dim l_max, and while
        orthonormalizing each tensor block, we generate the respective orthonormal matrices from slices of the full
        overlap matrix.

        Returns:
            S: 2D array. The overlap matrix
        """
        max_deg = np.max(
            np.arange(self.max_angular + 1) + 2 * np.array(self.num_radial_functions)
        )
        n_grid = np.arange(max_deg)
        sigma = self.radial_gaussian_width
        sigma_grid = np.ones(max_deg) * sigma
        S = gto_overlap(
            n_grid[:, np.newaxis],
            n_grid[np.newaxis, :],
            sigma_grid[:, np.newaxis],
            sigma_grid[np.newaxis, :],
        )
        return S

    def orthonormalize_basis(self, features: TensorMap):
        """
        Apply an in-place orthonormalization on the features, using Lodwin Symmetric Orthonormalization.
        Each block in the features TensorMap uses a GTO set of l + 2n, so we must take the appropriate slices of
        the overlap matrix to compute the orthonormalization matrix.
        An instructive example of Lodwin Symmetric Orthonormalization of a 2-element basis set is found here:
        https://booksite.elsevier.com/9780444594365/downloads/16755_10030.pdf

        Parameters:
            features: A TensorMap whose blocks' values we wish to orthonormalize. Note that features is modified in place, so a
            copy of features must be made before the function if you wish to retain the unnormalized values.
            radial_basis: An instance of _RadialBasis

        Returns:
            normalized_features: features containing values multiplied by proper normalization factors.
        """
        # In-place modification.
        radial_basis_name = self.radial_basis

        for label, block in features.items():
            # Each block's `properties` dimension contains radial channels for each neighbor species
            # Hence we have to iterate through each neighbor species and orthonormalize the block in subblocks
            # Each subblock is indexed using the neighbor_mask boolean array.
            neighbors = np.unique(block.properties["neighbor_species"])
            for neighbor in neighbors:
                l = label["angular_channel"]
                neighbor_mask = block.properties["neighbor_species"] == neighbor
                n_arr = block.properties["n"][neighbor_mask].flatten()
                l_2n_arr = l + 2 * n_arr
                # normalize all the GTOs by the appropriate prefactor first, since the overlap matrix is in terms of
                # normalized GTOs
                prefactor_arr = gto_prefactor(l_2n_arr, self.radial_gaussian_width)
                block.values[:, :, neighbor_mask] *= prefactor_arr

                gto_overlap_matrix_slice = self.overlap_matrix[l_2n_arr, :][:, l_2n_arr]
                orthonormalization_matrix = inverse_matrix_sqrt(
                    gto_overlap_matrix_slice, self.rcond, self.tol
                )
                block.values[:, :, neighbor_mask] = np.einsum(
                    "ijk,kl->ijl",
                    block.values[:, :, neighbor_mask],
                    orthonormalization_matrix,
                )

        return features

    def get_basis(self, rs):
        from matplotlib import pyplot as plt

        all_gs = np.empty(shape=(len(rs), 1))
        for l in range(0, self.max_angular):
            n_arr = np.arange(self.num_radial_functions[l])
            l_2n_arr = l + 2 * n_arr

            gs = np.array(
                [
                    (rs ** (2 * n + l))
                    * np.exp(-(rs**2.0) / (2 * self.radial_gaussian_width**2.0))
                    for n in n_arr
                ]
            ).T

            prefactor_arr = gto_prefactor(l_2n_arr, self.radial_gaussian_width)

            gs *= prefactor_arr

            gto_overlap_matrix_slice = self.overlap_matrix[l_2n_arr, :][:, l_2n_arr]
            orthonormalization_matrix = inverse_matrix_sqrt(
                gto_overlap_matrix_slice, self.rcond, self.tol
            )
            gs = np.einsum(
                "jk,kl->jl",
                gs,
                orthonormalization_matrix,
            )

            all_gs = np.hstack((all_gs, gs))
        return all_gs[:, 1:]


class ShiftedGTORadialBasis(_RadialBasis):
    def __init__(
        self,
        max_angular,
        cutoff_radius,
        *,
        radial_gaussian_width,
        radial_gaussian_shift,
        max_radial=None,
        rcond=1e-8,
        tol=1e-3,
    ):
        super().__init__(
            "shifted_gto", max_angular, cutoff_radius, max_radial, rcond, tol
        )
        self.radial_gaussian_width = radial_gaussian_width
        self.radial_gaussian_shift = radial_gaussian_shift

        # As part of the initialization, compute the orthonormalization matrix for GTOs
        # If we are using the monomial basis, set self.overlap_matrix equal to None
        self.overlap_matrix = self.calc_overlap_matrix()

    # For each particle pair (i,j), we are provided with the three quantities
    # that completely define the Gaussian distribution, namely
    # the pair distance r_ij, the rotation matrix specifying the orientation
    # of particle j's ellipsoid, as well the the three lengths of the
    # principal axes.
    # Combined with the choice of radial basis, these completely specify
    # the mathematical problem, namely the integral that needs to be
    # computed, which will be of the form
    # integral gaussian(x,y,z) * polynomial(x,y,z) dx dy dz
    # This function deals with the Gaussian part, which is specified
    # by a precision matrix (inverse of covariance) and its center.
    # The current function computes the covariance matrix and the center
    # for the provided parameters as well as choice of radial basis.
    def compute_gaussian_parameters(self, r_ij, lengths, rotation_matrix):
        # Initialization
        center = r_ij
        diag = np.diag(1 / lengths**2)
        precision = rotation_matrix @ diag @ rotation_matrix.T

        # GTO basis with uniform Gaussian width in the basis functions
        sigma = self.radial_gaussian_width
        precision += np.eye(3) / sigma**2
        center -= (
            1
            / sigma**2
            * np.linalg.solve(precision, r_ij + self.radial_gaussian_shift)
        )

        return precision, center

    def calc_overlap_matrix(self):
        """
        Computes the overlap matrix for GTOs.
        The overlap matrix is a Gram matrix whose entries are the overlap: S_{ij} = \int_0^\infty dr r^2 phi_i phi_j
        The overlap has an analytic solution (see above functions).
        The overlap matrix is the first step to generating an orthonormal basis set of functions (Lodwin Symmetric
        Orthonormalization). The actual orthonormalization matrix cannot be fully precomputed because each tensor
        block use a different set of GTOs. Hence, we precompute the full overlap matrix of dim l_max, and while
        orthonormalizing each tensor block, we generate the respective orthonormal matrices from slices of the full
        overlap matrix.

        Returns:
            S: 2D array. The overlap matrix
        """
        max_deg = np.max(
            np.arange(self.max_angular + 1) + 2 * np.array(self.num_radial_functions)
        )
        n_grid = np.arange(max_deg)
        sigma_grid = np.ones(max_deg) * self.radial_gaussian_width
        s_grid = np.ones(max_deg) * self.radial_gaussian_shift
        S = shifted_gto_overlap(
            n_grid[:, np.newaxis],
            n_grid[np.newaxis, :],
            sigma_grid[:, np.newaxis],
            sigma_grid[np.newaxis, :],
            s_grid[:, np.newaxis],
            s_grid[np.newaxis, :],
        )
        return S

    def orthonormalize_basis(self, features: TensorMap):
        """
        Apply an in-place orthonormalization on the features, using Lodwin Symmetric Orthonormalization.
        Each block in the features TensorMap uses a GTO set of l + 2n, so we must take the appropriate slices of
        the overlap matrix to compute the orthonormalization matrix.
        An instructive example of Lodwin Symmetric Orthonormalization of a 2-element basis set is found here:
        https://booksite.elsevier.com/9780444594365/downloads/16755_10030.pdf

        Parameters:
            features: A TensorMap whose blocks' values we wish to orthonormalize. Note that features is modified in place, so a
            copy of features must be made before the function if you wish to retain the unnormalized values.
            radial_basis: An instance of _RadialBasis

        Returns:
            normalized_features: features containing values multiplied by proper normalization factors.
        """

        for label, block in features.items():
            # Each block's `properties` dimension contains radial channels for each neighbor species
            # Hence we have to iterate through each neighbor species and orthonormalize the block in subblocks
            # Each subblock is indexed using the neighbor_mask boolean array.
            neighbors = np.unique(block.properties["neighbor_species"])
            for neighbor in neighbors:
                l = label["angular_channel"]
                neighbor_mask = block.properties["neighbor_species"] == neighbor
                n_arr = block.properties["n"][neighbor_mask].flatten()
                l_2n_arr = l + 2 * n_arr
                # normalize all the GTOs by the appropriate prefactor first, since the overlap matrix is in terms of
                # normalized GTOs
                prefactor_arr = shifted_gto_prefactor(
                    l_2n_arr, self.radial_gaussian_width, self.radial_gaussian_shift
                )
                block.values[:, :, neighbor_mask] *= prefactor_arr

                shifted_gto_overlap_matrix_slice = self.overlap_matrix[l_2n_arr, :][
                    :, l_2n_arr
                ]
                orthonormalization_matrix = inverse_matrix_sqrt(
                    shifted_gto_overlap_matrix_slice, self.rcond, self.tol
                )
                block.values[:, :, neighbor_mask] = np.einsum(
                    "ijk,kl->ijl",
                    block.values[:, :, neighbor_mask],
                    orthonormalization_matrix,
                )

        return features

    def get_basis(self, rs):
        from matplotlib import pyplot as plt

        all_gs = np.empty(shape=(len(rs), 1))
        for l in range(0, self.max_angular):
            n_arr = np.arange(self.num_radial_functions[l])
            l_2n_arr = l + 2 * n_arr

            gs = np.array(
                [
                    (rs ** (2 * n + l))
                    * np.exp(
                        -((rs - self.radial_gaussian_shift) ** 2.0)
                        / (2 * self.radial_gaussian_width**2.0)
                    )
                    for n in n_arr
                ]
            ).T

            prefactor_arr = shifted_gto_prefactor(
                l_2n_arr, self.radial_gaussian_width, self.radial_gaussian_shift
            )

            gs *= prefactor_arr

            shifted_gto_overlap_matrix_slice = self.overlap_matrix[l_2n_arr, :][
                :, l_2n_arr
            ]
            orthonormalization_matrix = inverse_matrix_sqrt(
                shifted_gto_overlap_matrix_slice, self.rcond, self.tol
            )
            gs = np.einsum(
                "jk,kl->jl",
                gs,
                orthonormalization_matrix,
            )

            all_gs = np.hstack((all_gs, gs))
        return all_gs[:, 1:]
