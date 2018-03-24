"""HabitatPatch BiotaEvolver object.
"""

from copy import deepcopy
from landlab.components.biota_macroevolution import (BiotaEvolverObject,
                                                     HabitatPatchVector)
from landlab.utils.watershed import get_watershed_masks_with_area_threshold
import numpy as np
from random import random
from uuid import uuid4


class HabitatPatch(BiotaEvolverObject):
    """The nodes and attributes of the entities that species populate.

    A universally unique identifier (UUID) is assigned to the habitat patch at
    initialization.
    """

    def __init__(self, mask):
        """
        Parameters
        ----------
        mask : boolean ndarray
            The initial mask of the habitat patch. True elements of this
            array correspond to the nodes of the habitat patch.
        """
        BiotaEvolverObject.__init__(self)
        self.mask = mask
        self._identifier = uuid4()
        self.species = []
        self.plot_color = (random(), random(), random(), 1)

    @classmethod
    def _get_habitat_patch_vectors(cls, prior_patches, new_patches, time, grid,
                                   **kwargs):
        """Identify habitat patch connectivity across two timesteps.

        Habitat patch vectors describe the temporal connectivity of habitat
        patches. The returned dictionary includes all of the vectors of the
        inputted patches. The origin of a vector is a prior patch. The
        destinations of a vector are the patches that spatially intersect the
        prior patch.

        Habitat patch vectors are determined by the number of patch
        intersections between the prior and current timesteps. Here,
        cardinality refers to these intersections and is designated by a string
        with the pattern, x-to-y where x and y are the descriptive counts
        (none, one, or many) of patch(es) at the prior and current timestep,
        respectively. For example, a cardinality of one-to-many is a habitat
        patch in the prior timestep that was fragmented into many habitat
        patches in the current timestep.

        In any of the `many` cardinality cases, a rule determines which of the
        prior patches persist as the patch in the current timestep. The patch
        with the greatest area of intersection between the prior and current
        timesteps persists to the current timestep along with the others in
        `new_patches`.

        Parameters
        ----------
        prior_patches : HabitatPatch list
            The habitat patches of the prior timestep.
        new_patches : HabitatPatch list
            The habitat patches of the current timestep.
        time : float
            The current simulation time.
        grid : ModelGrid
            A Landlab ModelGrid.

        Returns
        -------
        vectors : BiotaEvolver HabitatPatchVector list
            A list of BiotaEvolver HabitatPatchVector objects with attributes
            that link habitat patches over time.
        be_record_supplement : dictionary
            The items of this dictionary will become items in the BiotaEvolver
            record for this time.
        """
        vectors = []

        # Stack the masks for prior (p) and new (n) habitat patches.
        ps = np.vstack((p.mask for p in prior_patches))
        ns = np.vstack((n.mask for n in new_patches))

        # Keep track of new patches replaced by prior patches. Patch in the
        # dictionary key will be replaced by their values after the prior
        # patches are processed.
        replacements = {}

        # New patches that do not intersect prior patches will be process after
        # the prior patches.
        new_overlap_not_found = deepcopy(new_patches)

        # The cumulation of captured grid area for habitat patched is retained
        # in order to add it to be_record_supplement after all patches are
        # processed.
        number_of_captures = 0
        cum_area_captured = 0
        cell_area = grid.dx * grid.dy

        for p in prior_patches:
            # Get the new patches that overlap the prior patch.
            p_in_ns = np.all([p.mask == ns, ns], 0)
            n_indices = np.argwhere(p_in_ns)
            n_indices = np.unique(n_indices[:, 0])
            n_overlaps_p = [new_patches[i] for i in n_indices]
            n_overlaps_p_count = len(n_indices)

            # Get the prior patch that is overlapped by the new patches.
            if n_overlaps_p_count > 0:
                n = new_patches[n_indices[0]]
                n_nodes = n.mask
                n_in_ps = np.all([n_nodes == ps, ps], 0)
                p_indices = np.argwhere(n_in_ps)
                p_indices = np.unique(p_indices[:, 0])
                p_overlaps_n = [prior_patches[i] for i in p_indices]
                p_overlaps_n_count = len(p_indices)
            else:
                p_overlaps_n_count = 1

            # The new patches that overlapped this p can be deleted. They
            # cannot have none-to-one cardinality because they intersect at
            # least this p.
            delete = np.where(new_overlap_not_found == n_overlaps_p)
            new_overlap_not_found = np.delete(new_overlap_not_found,
                                              new_overlap_not_found == delete)

            v = HabitatPatchVector(p_overlaps_n_count, n_overlaps_p_count)

            # Build vector depending upon habitat patch stepwise cardinality.
            if v.cardinality == HabitatPatchVector.ONE_TO_NONE:
                destinations = []

            elif v.cardinality == HabitatPatchVector.ONE_TO_ONE:
                # The prior patch is set as the new patch
                # because only the one new and the one prior overlap.
                p.mask = n.mask
                destinations = [p]

                replacements[n] = p

            elif v.cardinality == HabitatPatchVector.ONE_TO_MANY:
                # Set the destinations to the new patches that overlap p.
                # Although, replace the dominant n with p.
                dominant_n = p._get_largest_intersection(n_overlaps_p)
                p.mask = dominant_n.mask
                n_overlaps_p[n_overlaps_p.index(dominant_n)] = p
                destinations = n_overlaps_p

                replacements[dominant_n] = p

            elif v.cardinality == HabitatPatchVector.MANY_TO_ONE:
                # Set the destination to the prior patch that intersects n the
                # most.
                dominant_p = n._get_largest_intersection(p_overlaps_n)
                dominant_p.mask = n.mask
                destinations = [dominant_p]

                replacements[n] = dominant_p

            elif v.cardinality == HabitatPatchVector.MANY_TO_MANY:
                # Get the new patch that intersects p the most.
                dominant_n = p._get_largest_intersection(n_overlaps_p)
                dominant_n_nodes = dominant_n.mask
                dominant_n_in_ps = np.all([dominant_n_nodes == ps, ps], 0)

                # Get the prior patch that intersects the dominant n the most.
                p_indices = np.argwhere(dominant_n_in_ps)
                p_indices = np.unique(p_indices[:, 0])
                p_of_dominant_n = [prior_patches[i] for i in p_indices]
                dominant_p = dominant_n._get_largest_intersection(p_of_dominant_n)

                # Set the destination to the n that overlaps p. Although, the
                # p that greatest intersects the dominant n replaces the
                # dominant n in the destination list.
                dominant_p.mask = dominant_n.mask
                n_overlaps_p[n_overlaps_p.index(dominant_n)] = dominant_p
                destinations = n_overlaps_p

                replacements[dominant_n] = dominant_p

            # Update the capture statistics.
            if v.cardinality in [HabitatPatchVector.ONE_TO_MANY,
                                 HabitatPatchVector.MANY_TO_MANY]:
                number_of_captures += len(n_overlaps_p)

                for n_i in n_overlaps_p:
                    captured_nodes = np.all([p.mask, n_i.mask], 0)
                    number_of_captured_nodes = len(np.where(captured_nodes))
                    cum_area_captured += number_of_captured_nodes * cell_area

            v.origin = p
            v.destinations = destinations
            vectors.append(v)

        # Handle new habitat patches that did not overlap prior patches.
        for n in new_overlap_not_found:
            v = HabitatPatchVector(0, 1)
            v.destinations = [n]

        # Update patches that were replaced using the dominant patches above.
        for patch in replacements.keys():
            for v in vectors:
                for i,d in enumerate(v.destinations):
                    if d == patch:
                        v.destinations[i] = replacements[patch]

        if 'vector_filepath' in kwargs:
            cls._write_vector_file(vectors, time, kwargs['vector_filepath'])

        be_record_supplement = {'number_of_captures': number_of_captures,
                                'sum_of_area_captured': cum_area_captured}

        return vectors, be_record_supplement

    @classmethod
    def _write_vector_file(cls, vectors, time, filepath):
        """Write habitat patch vectors to an ascii file.

        This method writes `vectors` at `time`. Vector data are appended to the
        output file if it exists. The time will be written to the next line of
        the output file designated by `path`. Each vector will be written to
        a subsequent line below the time. The first element of a vector line is
        the origin id. The subsequent elements are the destinations ids. All
        ids are comma-seperated.
        """
        f = open(filepath, 'a')

        f.write('{}\n'.format(time))

        for v in vectors:
            if v.origin == None:
                o = ''
            else:
                o = v.origin.identifier

            d = [str(d.identifier) for d in v.destinations]
            d = ','.join(d)
            f.write('{},{},{}\n'.format(v.cardinality, o, d))

        f.close()

    def _get_largest_intersection(self, patches):
        nodes = self.mask
        n_patch_overlap_nodes = []
        for p in patches:
            n = len(np.where(np.all([p.mask, nodes], 0))[0])
            n_patch_overlap_nodes.append(n)

        return patches[np.argmax(n_patch_overlap_nodes)]

    @staticmethod
    def get_patches_with_area_threshold(grid, area_threshold):

        grid.at_node['watershed'] = get_watershed_masks_with_area_threshold(
                grid, area_threshold)
        outlets = np.unique(grid.at_node['watershed'])
        outlets = np.delete(outlets, np.where(outlets == -1))

        patches = []

        stream_mask = grid.at_node['drainage_area'] >= 1e6

        for outlet in outlets:
            watershed_mask = grid.at_node['watershed'] == outlet
            patch_mask = np.all([watershed_mask, stream_mask], 0)
            patches.append(HabitatPatch(patch_mask))

        return patches
